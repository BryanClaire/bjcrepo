from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ComicNotFound(Exception):
    """Raised when a requested comic does not exist."""


class InvalidComicUpdate(Exception):
    """Raised when an update violates the comic's domain rules."""


@dataclass
class DuplicateComics(Exception):
    matches: list[dict[str, Any]]

    def __str__(self) -> str:
        return "One or more likely duplicate comics were found."
