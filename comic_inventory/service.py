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

    def list_comics(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        return self.repository.list_comics(include_deleted=include_deleted)

    def update_comic(
        self, comic_id: int, updates: dict[str, Any], quantity_note: str | None = None
    ) -> dict[str, Any]:
        return self.repository.update_comic(comic_id, updates, quantity_note)

    def set_deleted(self, comic_id: int, deleted: bool) -> dict[str, Any]:
        return self.repository.set_deleted(comic_id, deleted)
