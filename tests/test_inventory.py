from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from comic_inventory.api import create_app
from comic_inventory.database import Database


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "comics.db")
    with TestClient(app) as test_client:
        yield test_client


def comic_payload(**overrides):
    payload = {
        "series_title": "Saga",
        "issue_number": "1",
        "publisher": "Image Comics",
        "publication_year": 2012,
        "variant": "Cover A",
        "grade": "9.4",
        "quantity": 2,
        "upc": "709853012345",
        "creators": "Brian K. Vaughan, Fiona Staples",
        "condition_notes": "Light spine wear",
        "purchase_cost": 4.5,
        "purchase_date": "2024-06-15",
        "purchase_source": "Local shop",
        "storage_location": "Long box 1",
    }
    payload.update(overrides)
    return payload


def add_comic(client, **overrides):
    response = client.post("/api/comics", json=comic_payload(**overrides))
    assert response.status_code == 201
    return response.json()["comic"]


def test_create_read_and_update_comic(client):
    created = add_comic(client)

    listed = client.get("/api/comics").json()["items"]
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]

    details = client.get(f"/api/comics/{created['id']}").json()
    assert details["creators"] == "Brian K. Vaughan, Fiona Staples"
    assert details["movements"][0]["movement_type"] == "initial_entry"
    assert details["movements"][0]["quantity_delta"] == 2

    updated = client.patch(
        f"/api/comics/{created['id']}",
        json={"quantity": 5, "storage_location": "Long box 2", "quantity_note": "Found extras"},
    )
    assert updated.status_code == 200
    assert updated.json()["quantity"] == 5
    assert updated.json()["storage_location"] == "Long box 2"
    movement = client.get(f"/api/comics/{created['id']}").json()["movements"][-1]
    assert movement["movement_type"] == "adjustment"
    assert movement["quantity_delta"] == 3
    assert movement["notes"] == "Found extras"


def test_duplicate_warning_continue_and_merge(client):
    first = add_comic(client)

    warning = client.post("/api/comics", json=comic_payload(quantity=3))
    assert warning.status_code == 409
    assert warning.json()["detail"]["code"] == "duplicate"
    assert warning.json()["detail"]["comics"][0]["id"] == first["id"]

    merged = client.post(
        "/api/comics?duplicate_action=merge", json=comic_payload(quantity=3)
    )
    assert merged.status_code == 200
    assert merged.json()["merged"] is True
    assert merged.json()["comic"]["quantity"] == 5
    assert len(client.get("/api/comics").json()["items"]) == 1
    merge_movement = client.get(f"/api/comics/{first['id']}").json()["movements"][-1]
    assert merge_movement["notes"] == "Merged duplicate inventory entry"

    separate = client.post(
        "/api/comics?duplicate_action=continue", json=comic_payload(quantity=1)
    )
    assert separate.status_code == 201
    assert separate.json()["merged"] is False
    assert len(client.get("/api/comics").json()["items"]) == 2


def test_negative_quantity_is_rejected(client):
    rejected_create = client.post("/api/comics", json=comic_payload(quantity=-1))
    assert rejected_create.status_code == 422
    comic = add_comic(client)
    rejected_update = client.patch(
        f"/api/comics/{comic['id']}", json={"quantity": -1}
    )
    assert rejected_update.status_code == 422
    assert client.get(f"/api/comics/{comic['id']}").json()["quantity"] == 2


def test_sqlite_quantity_constraint_and_migrations_are_durable(client, tmp_path):
    comic = add_comic(client)
    database = client.app.state.comic_repository.database
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE comics SET quantity = -1 WHERE id = ?", (comic["id"],)
            )

    migrated_database = Database(tmp_path / "idempotent.db")
    migrated_database.initialize()
    migrated_database.initialize()
    with migrated_database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM comics").fetchone()[0] == 0


def test_required_fields_cannot_be_blank_or_cleared(client):
    blank = client.post("/api/comics", json=comic_payload(series_title="   "))
    assert blank.status_code == 422
    comic = add_comic(client)
    cleared = client.patch(f"/api/comics/{comic['id']}", json={"publisher": None})
    assert cleared.status_code == 422
    empty_quantity = client.patch(f"/api/comics/{comic['id']}", json={"quantity": None})
    assert empty_quantity.status_code == 422


def test_soft_delete_restoration_and_movement_history(client):
    comic = add_comic(client, quantity=4)
    deleted = client.delete(f"/api/comics/{comic['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None
    assert client.get("/api/comics").json()["items"] == []
    assert len(client.get("/api/comics?include_deleted=true").json()["items"]) == 1

    restored = client.post(f"/api/comics/{comic['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert len(client.get("/api/comics").json()["items"]) == 1
    movements = client.get(f"/api/comics/{comic['id']}").json()["movements"]
    assert [movement["movement_type"] for movement in movements] == [
        "initial_entry",
        "deletion",
        "restoration",
    ]


def test_duplicate_match_ignores_case_and_surrounding_whitespace(client):
    add_comic(client)
    duplicate = client.post(
        "/api/comics",
        json=comic_payload(
            series_title="  SAGA ",
            publisher="IMAGE COMICS ",
            variant="cover a",
            grade="9.4 ",
        ),
    )
    assert duplicate.status_code == 409


def test_cover_upload_and_invalid_media_type(client):
    comic = add_comic(client)
    uploaded = client.post(
        f"/api/comics/{comic['id']}/cover",
        files={"file": ("cover.png", b"fake png", "image/png")},
    )
    assert uploaded.status_code == 200
    cover_name = uploaded.json()["cover_image_path"]
    assert len(cover_name) == 36

    invalid = client.post(
        f"/api/comics/{comic['id']}/cover",
        files={"file": ("cover.svg", b"<svg/>", "image/svg+xml")},
    )
    assert invalid.status_code == 415
