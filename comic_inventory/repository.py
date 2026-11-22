from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from comic_inventory.database import Database
from comic_inventory.domain import ComicNotFound, InvalidComicUpdate


COMIC_FIELDS = (
    "series_title",
    "issue_number",
    "publisher",
    "publication_year",
    "variant",
    "grade",
    "quantity",
    "upc",
    "creators",
    "condition_notes",
    "purchase_cost",
    "purchase_date",
    "purchase_source",
    "storage_location",
)
REQUIRED_FIELDS = ("series_title", "issue_number", "publisher", "grade")


def natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )


def natural_compare(left: str, right: str) -> int:
    left_key = natural_key(left)
    right_key = natural_key(right)
    return (left_key > right_key) - (left_key < right_key)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class ComicRepository:
    def __init__(self, database: Database):
        self.database = database

    def browse_comics(
        self,
        *,
        search: str | None,
        publisher: str | None,
        grade: str | None,
        year: int | None,
        variant: str | None,
        storage_location: str | None,
        sort_by: str,
        sort_order: str,
        limit: int,
        offset: int,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if not include_deleted:
            conditions.append("deleted_at IS NULL")
        if search and search.strip():
            searchable_fields = (
                "series_title",
                "issue_number",
                "publisher",
                "variant",
                "grade",
                "upc",
                "creators",
                "storage_location",
            )
            terms = " OR ".join(
                f"instr(lower(coalesce({field}, '')), lower(?)) > 0"
                for field in searchable_fields
            )
            conditions.append(f"({terms})")
            parameters.extend([search.strip()] * len(searchable_fields))
        for column, value in (
            ("publisher", publisher),
            ("grade", grade),
            ("variant", variant),
            ("storage_location", storage_location),
        ):
            if value and value.strip():
                conditions.append(f"lower(trim({column})) = lower(trim(?))")
                parameters.append(value.strip())
        if year is not None:
            conditions.append("publication_year = ?")
            parameters.append(year)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sort_columns = {
            "series_title": "series_title COLLATE NOCASE",
            "issue_number": "issue_number COLLATE COMIC_NATURAL",
            "publisher": "publisher COLLATE NOCASE",
            "publication_year": "publication_year",
            "grade": "grade COLLATE NOCASE",
            "quantity": "quantity",
        }
        direction = "DESC" if sort_order == "desc" else "ASC"
        sort_expression = sort_columns[sort_by]
        nulls = " NULLS LAST" if sort_by == "publication_year" else ""
        order_by = [f"{sort_expression} {direction}{nulls}"]
        if sort_by != "series_title":
            order_by.append("series_title COLLATE NOCASE ASC")
        if sort_by != "issue_number":
            order_by.append("issue_number COLLATE COMIC_NATURAL ASC")
        order_by.append("id ASC")

        with self.database.connection() as connection:
            connection.create_collation("COMIC_NATURAL", natural_compare)
            total = connection.execute(
                f"SELECT COUNT(*) FROM comics {where}", parameters
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM comics {where}
                ORDER BY {", ".join(order_by)}
                LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()
            items = [dict(row) for row in rows]
            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(items) < total,
            }

    def list_facets(self, include_deleted: bool = False) -> dict[str, list[Any]]:
        with self.database.connection() as connection:
            deleted_clause = "" if include_deleted else "AND deleted_at IS NULL"

            def text_values(column: str) -> list[str]:
                rows = connection.execute(
                    f"""
                    SELECT DISTINCT trim({column}) AS value
                    FROM comics
                    WHERE trim(coalesce({column}, '')) <> '' {deleted_clause}
                    ORDER BY value COLLATE NOCASE
                    """
                ).fetchall()
                return [row["value"] for row in rows]

            years = connection.execute(
                f"""
                SELECT DISTINCT publication_year AS value
                FROM comics
                WHERE publication_year IS NOT NULL {deleted_clause}
                ORDER BY value DESC
                """
            ).fetchall()
            return {
                "publishers": text_values("publisher"),
                "grades": text_values("grade"),
                "variants": text_values("variant"),
                "storage_locations": text_values("storage_location"),
                "years": [row["value"] for row in years],
            }

    def get_collection_summary(self) -> dict[str, int | float]:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS comic_count,
                    COALESCE(SUM(quantity), 0) AS total_copies,
                    COUNT(DISTINCT lower(trim(series_title))) AS series_count,
                    COUNT(DISTINCT lower(trim(publisher))) AS publisher_count,
                    COALESCE(SUM(CASE
                        WHEN purchase_cost IS NULL THEN 0
                        ELSE purchase_cost * quantity
                    END), 0) AS known_purchase_cost
                FROM comics
                WHERE deleted_at IS NULL
                """
            ).fetchone()
            return dict(row)

    def get_comic(self, comic_id: int) -> dict[str, Any]:
        with self.database.connection() as connection:
            comic = as_dict(
                connection.execute(
                    "SELECT * FROM comics WHERE id = ?", (comic_id,)
                ).fetchone()
            )
            if comic is None:
                raise ComicNotFound
            return comic

    def find_duplicates(self, comic: dict[str, Any]) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM comics
                WHERE deleted_at IS NULL
                  AND lower(trim(series_title)) = lower(trim(?))
                  AND lower(trim(issue_number)) = lower(trim(?))
                  AND lower(trim(publisher)) = lower(trim(?))
                  AND lower(trim(variant)) = lower(trim(?))
                  AND lower(trim(grade)) = lower(trim(?))
                ORDER BY id
                """,
                (
                    comic["series_title"],
                    comic["issue_number"],
                    comic["publisher"],
                    comic.get("variant") or "",
                    comic["grade"],
                ),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_comic(self, comic: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        fields = [field for field in COMIC_FIELDS if field in comic]
        values = [comic[field] for field in fields]
        placeholders = ", ".join("?" for _ in fields)
        with self.database.connection() as connection:
            with connection:
                cursor = connection.execute(
                    f"""
                    INSERT INTO comics ({", ".join(fields)}, created_at, updated_at)
                    VALUES ({placeholders}, ?, ?)
                    """,
                    (*values, now, now),
                )
                comic_id = cursor.lastrowid
                quantity = comic.get("quantity", 1)
                connection.execute(
                    """
                    INSERT INTO inventory_movements
                        (comic_id, movement_type, quantity_delta, quantity_after, notes, created_at)
                    VALUES (?, 'initial_entry', ?, ?, 'Initial inventory entry', ?)
                    """,
                    (comic_id, quantity, quantity, now),
                )
            return self.get_comic(comic_id)

    def merge_quantity(self, comic_id: int, amount: int) -> dict[str, Any]:
        now = utc_now()
        with self.database.connection() as connection:
            with connection:
                current = connection.execute(
                    "SELECT quantity, deleted_at FROM comics WHERE id = ?", (comic_id,)
                ).fetchone()
                if current is None or current["deleted_at"] is not None:
                    raise ComicNotFound
                quantity_after = current["quantity"] + amount
                connection.execute(
                    "UPDATE comics SET quantity = ?, updated_at = ? WHERE id = ?",
                    (quantity_after, now, comic_id),
                )
                connection.execute(
                    """
                    INSERT INTO inventory_movements
                        (comic_id, movement_type, quantity_delta, quantity_after, notes, created_at)
                    VALUES (?, 'adjustment', ?, ?, 'Merged duplicate inventory entry', ?)
                    """,
                    (comic_id, amount, quantity_after, now),
                )
            return self.get_comic(comic_id)

    def update_comic(
        self, comic_id: int, updates: dict[str, Any], quantity_note: str | None = None
    ) -> dict[str, Any]:
        unknown = set(updates) - set(COMIC_FIELDS)
        if unknown:
            raise InvalidComicUpdate(f"Unsupported fields: {', '.join(sorted(unknown))}")
        if any(updates[field] is None for field in REQUIRED_FIELDS if field in updates):
            raise InvalidComicUpdate("Series title, issue number, publisher, and grade are required.")
        if any(not str(updates[field]).strip() for field in REQUIRED_FIELDS if field in updates):
            raise InvalidComicUpdate("Series title, issue number, publisher, and grade cannot be blank.")
        if "quantity" in updates and updates["quantity"] is None:
            raise InvalidComicUpdate("Quantity cannot be blank.")
        now = utc_now()
        with self.database.connection() as connection:
            with connection:
                current = connection.execute(
                    "SELECT * FROM comics WHERE id = ? AND deleted_at IS NULL",
                    (comic_id,),
                ).fetchone()
                if current is None:
                    raise ComicNotFound
                old_quantity = current["quantity"]
                new_quantity = updates.get("quantity", old_quantity)
                if not updates:
                    return dict(current)
                assignments = ", ".join(f"{field} = ?" for field in updates)
                connection.execute(
                    f"UPDATE comics SET {assignments}, updated_at = ? WHERE id = ?",
                    (*updates.values(), now, comic_id),
                )
                if new_quantity != old_quantity:
                    note = quantity_note or f"Quantity changed from {old_quantity} to {new_quantity}"
                    connection.execute(
                        """
                        INSERT INTO inventory_movements
                            (comic_id, movement_type, quantity_delta, quantity_after, notes, created_at)
                        VALUES (?, 'adjustment', ?, ?, ?, ?)
                        """,
                        (comic_id, new_quantity - old_quantity, new_quantity, note, now),
                    )
            return self.get_comic(comic_id)

    def set_cover(self, comic_id: int, filename: str) -> dict[str, Any]:
        now = utc_now()
        with self.database.connection() as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE comics SET cover_image_path = ?, updated_at = ?
                    WHERE id = ? AND deleted_at IS NULL
                    """,
                    (filename, now, comic_id),
                )
                if cursor.rowcount == 0:
                    raise ComicNotFound
            return self.get_comic(comic_id)

    def set_deleted(self, comic_id: int, deleted: bool) -> dict[str, Any]:
        now = utc_now()
        movement = "deletion" if deleted else "restoration"
        with self.database.connection() as connection:
            with connection:
                current = connection.execute(
                    "SELECT quantity, deleted_at FROM comics WHERE id = ?", (comic_id,)
                ).fetchone()
                if current is None:
                    raise ComicNotFound
                if deleted == (current["deleted_at"] is not None):
                    return dict(
                        connection.execute(
                            "SELECT * FROM comics WHERE id = ?", (comic_id,)
                        ).fetchone()
                    )
                deleted_at = now if deleted else None
                connection.execute(
                    "UPDATE comics SET deleted_at = ?, updated_at = ? WHERE id = ?",
                    (deleted_at, now, comic_id),
                )
                connection.execute(
                    """
                    INSERT INTO inventory_movements
                        (comic_id, movement_type, quantity_delta, quantity_after, notes, created_at)
                    VALUES (?, ?, 0, ?, ?, ?)
                    """,
                    (
                        comic_id,
                        movement,
                        current["quantity"],
                        "Item soft-deleted" if deleted else "Item restored",
                        now,
                    ),
                )
            return self.get_comic(comic_id)

    def list_movements(self, comic_id: int) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM inventory_movements
                WHERE comic_id = ? ORDER BY created_at, id
                """,
                (comic_id,),
            ).fetchall()
            return [dict(row) for row in rows]
