from __future__ import annotations

from typing import Any, Literal

from comic_inventory.domain import ComicNotFound, DuplicateComics
from comic_inventory.repository import ComicRepository


DuplicateAction = Literal["continue", "merge"] | None


class ComicService:
    def __init__(self, repository: ComicRepository):
        self.repository = repository

    def create_comic(
        self, comic: dict[str, Any], duplicate_action: DuplicateAction = None
    ) -> tuple[dict[str, Any], bool]:
        matches = self.repository.find_duplicates(comic)
        if matches and duplicate_action is None:
            raise DuplicateComics(matches)
        if matches and duplicate_action == "merge":
            merged = self.repository.merge_quantity(matches[0]["id"], comic.get("quantity", 1))
            return merged, True
        return self.repository.create_comic(comic), False

    def get_comic(self, comic_id: int) -> dict[str, Any]:
        comic = self.repository.get_comic(comic_id)
        comic["movements"] = self.repository.list_movements(comic_id)
        return comic

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
        return self.repository.browse_comics(
            search=search,
            publisher=publisher,
            grade=grade,
            year=year,
            variant=variant,
            storage_location=storage_location,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
            include_deleted=include_deleted,
        )

    def list_facets(self, include_deleted: bool = False) -> dict[str, list[Any]]:
        return self.repository.list_facets(include_deleted=include_deleted)

    def get_collection_summary(self) -> dict[str, int | float]:
        return self.repository.get_collection_summary()

    def update_comic(
        self, comic_id: int, updates: dict[str, Any], quantity_note: str | None = None
    ) -> dict[str, Any]:
        return self.repository.update_comic(comic_id, updates, quantity_note)

    def set_deleted(self, comic_id: int, deleted: bool) -> dict[str, Any]:
        return self.repository.set_deleted(comic_id, deleted)
