from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from comic_inventory.database import Database
from comic_inventory.domain import ComicNotFound, DuplicateComics, InvalidComicUpdate
from comic_inventory.repository import ComicRepository
from comic_inventory.service import ComicService


ROOT_DIR = Path(__file__).resolve().parent.parent
MAX_COVER_BYTES = 10 * 1024 * 1024
ALLOWED_COVER_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class ComicCreate(BaseModel):
    series_title: str = Field(min_length=1, max_length=200)
    issue_number: str = Field(min_length=1, max_length=40)
    publisher: str = Field(min_length=1, max_length=120)
    publication_year: int | None = Field(default=None, ge=1, le=9999)
    variant: str = Field(default="", max_length=200)
    grade: str = Field(min_length=1, max_length=80)
    quantity: int = Field(default=1, ge=0)
    upc: str | None = Field(default=None, max_length=80)
    creators: str | None = Field(default=None, max_length=1000)
    condition_notes: str | None = Field(default=None, max_length=2000)
    purchase_cost: float | None = Field(default=None, ge=0)
    purchase_date: str | None = Field(default=None, max_length=30)
    purchase_source: str | None = Field(default=None, max_length=200)
    storage_location: str | None = Field(default=None, max_length=200)

    @field_validator("series_title", "issue_number", "publisher", "grade")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value


class ComicUpdate(BaseModel):
    series_title: str | None = Field(default=None, min_length=1, max_length=200)
    issue_number: str | None = Field(default=None, min_length=1, max_length=40)
    publisher: str | None = Field(default=None, min_length=1, max_length=120)
    publication_year: int | None = Field(default=None, ge=1, le=9999)
    variant: str | None = Field(default=None, max_length=200)
    grade: str | None = Field(default=None, min_length=1, max_length=80)
    quantity: int | None = Field(default=None, ge=0)
    upc: str | None = Field(default=None, max_length=80)
    creators: str | None = Field(default=None, max_length=1000)
    condition_notes: str | None = Field(default=None, max_length=2000)
    purchase_cost: float | None = Field(default=None, ge=0)
    purchase_date: str | None = Field(default=None, max_length=30)
    purchase_source: str | None = Field(default=None, max_length=200)
    storage_location: str | None = Field(default=None, max_length=200)
    quantity_note: str | None = Field(default=None, max_length=500)

    @field_validator("series_title", "issue_number", "publisher", "grade")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value


def create_app(database_path: str | Path | None = None) -> FastAPI:
    configured_path = database_path or os.environ.get(
        "COMIC_INVENTORY_DB", str(ROOT_DIR / "data" / "comics.db")
    )
    database = Database(configured_path)
    repository = ComicRepository(database)
    service = ComicService(repository)
    covers_directory = database.path.parent / "covers"
    covers_directory.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        yield

    app = FastAPI(title="Comic Inventory", version="0.1.0", lifespan=lifespan)
    app.state.comic_service = service
    app.state.comic_repository = repository
    app.state.covers_directory = covers_directory

    app.mount("/static", StaticFiles(directory=ROOT_DIR / "static"), name="static")
    app.mount("/covers", StaticFiles(directory=covers_directory), name="covers")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(ROOT_DIR / "static" / "index.html")

    @app.get("/api/comics")
    def list_comics(
        search: str | None = Query(default=None, max_length=200),
        publisher: str | None = Query(default=None, max_length=120),
        grade: str | None = Query(default=None, max_length=80),
        year: int | None = Query(default=None, ge=1, le=9999),
        variant: str | None = Query(default=None, max_length=200),
        storage_location: str | None = Query(default=None, max_length=200),
        sort_by: Literal[
            "series_title",
            "issue_number",
            "publisher",
            "publication_year",
            "grade",
            "quantity",
        ] = Query(default="series_title"),
        sort_order: Literal["asc", "desc"] = Query(default="asc"),
        limit: int = Query(default=24, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        include_deleted: bool = Query(default=False),
    ) -> dict[str, Any]:
        return service.browse_comics(
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

    @app.get("/api/comics/facets")
    def list_comic_facets(
        include_deleted: bool = Query(default=False),
    ) -> dict[str, list[Any]]:
        return service.list_facets(include_deleted=include_deleted)

    @app.get("/api/collection/summary")
    def get_collection_summary() -> dict[str, int | float]:
        return service.get_collection_summary()

    @app.post("/api/comics")
    def create_comic(
        payload: ComicCreate,
        response: Response,
        duplicate_action: Literal["continue", "merge"] | None = Query(default=None),
    ) -> dict[str, Any]:
        comic = payload.model_dump()
        try:
            created, merged = service.create_comic(comic, duplicate_action)
        except DuplicateComics as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "duplicate", "comics": error.matches},
            ) from error
        response.status_code = 200 if merged else 201
        return {"comic": created, "merged": merged}

    @app.get("/api/comics/{comic_id}")
    def get_comic(comic_id: int) -> dict[str, Any]:
        try:
            return service.get_comic(comic_id)
        except ComicNotFound as error:
            raise HTTPException(status_code=404, detail="Comic not found") from error

    @app.patch("/api/comics/{comic_id}")
    def update_comic(comic_id: int, payload: ComicUpdate) -> dict[str, Any]:
        values = payload.model_dump(exclude_unset=True)
        quantity_note = values.pop("quantity_note", None)
        try:
            return service.update_comic(comic_id, values, quantity_note)
        except ComicNotFound as error:
            raise HTTPException(status_code=404, detail="Comic not found") from error
        except InvalidComicUpdate as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.delete("/api/comics/{comic_id}")
    def delete_comic(comic_id: int) -> dict[str, Any]:
        try:
            return service.set_deleted(comic_id, True)
        except ComicNotFound as error:
            raise HTTPException(status_code=404, detail="Comic not found") from error

    @app.post("/api/comics/{comic_id}/restore")
    def restore_comic(comic_id: int) -> dict[str, Any]:
        try:
            return service.set_deleted(comic_id, False)
        except ComicNotFound as error:
            raise HTTPException(status_code=404, detail="Comic not found") from error

    @app.post("/api/comics/{comic_id}/cover")
    async def upload_cover(
        comic_id: int, file: UploadFile = File(...)
    ) -> dict[str, Any]:
        extension = ALLOWED_COVER_TYPES.get(file.content_type or "")
        if extension is None:
            raise HTTPException(status_code=415, detail="Cover must be JPEG, PNG, or WebP")
        contents = await file.read(MAX_COVER_BYTES + 1)
        if not contents or len(contents) > MAX_COVER_BYTES:
            raise HTTPException(status_code=413, detail="Cover image must be under 10 MB")
        try:
            comic = repository.get_comic(comic_id)
            if comic["deleted_at"] is not None:
                raise ComicNotFound
            filename = f"{uuid.uuid4().hex}{extension}"
            (covers_directory / filename).write_bytes(contents)
            return repository.set_cover(comic_id, filename)
        except ComicNotFound as error:
            raise HTTPException(status_code=404, detail="Comic not found") from error

    return app


app = create_app()
