from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from comic_inventory.api import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "browse.db")) as test_client:
        yield test_client


def add_comic(
    client,
    *,
    series_title="Saga",
    issue_number="1",
    publisher="Image Comics",
    publication_year=2012,
    variant="Cover A",
    grade="9.4",
    quantity=1,
    creators="Brian K. Vaughan, Fiona Staples",
    upc=None,
    storage_location="Long box 1",
    purchase_cost=None,
):
    response = client.post(
        "/api/comics",
        json={
            "series_title": series_title,
            "issue_number": issue_number,
            "publisher": publisher,
            "publication_year": publication_year,
            "variant": variant,
            "grade": grade,
            "quantity": quantity,
            "creators": creators,
            "upc": upc,
            "storage_location": storage_location,
            "purchase_cost": purchase_cost,
        },
    )
    assert response.status_code == 201
    return response.json()["comic"]


def test_search_matches_catalog_metadata(client):
    target = add_comic(client, upc="709853012345")
    add_comic(
        client,
        series_title="Detective Comics",
        issue_number="27",
        publisher="DC Comics",
        publication_year=1939,
        creators="Jerry Siegel",
    )

    creator_results = client.get("/api/comics", params={"search": "fiona staples"})
    assert creator_results.status_code == 200
    assert [comic["id"] for comic in creator_results.json()["items"]] == [target["id"]]

    upc_results = client.get("/api/comics", params={"search": "709853012"})
    assert [comic["id"] for comic in upc_results.json()["items"]] == [target["id"]]


def test_multiple_filters_are_combined(client):
    match = add_comic(client)
    add_comic(client, variant="Cover B", storage_location="Long box 1")
    add_comic(
        client,
        series_title="Detective Comics",
        issue_number="5",
        publisher="DC Comics",
        publication_year=2020,
        variant="Cover A",
        grade="8.0",
        storage_location="Long box 1",
    )

    response = client.get(
        "/api/comics",
        params={
            "publisher": "image comics",
            "grade": "9.4",
            "year": 2012,
            "variant": "Cover A",
            "storage_location": "Long box 1",
            "search": "Saga",
        },
    )
    assert response.status_code == 200
    assert [comic["id"] for comic in response.json()["items"]] == [match["id"]]

    facets = client.get("/api/comics/facets").json()
    assert facets["publishers"] == ["DC Comics", "Image Comics"]
    assert facets["years"] == [2020, 2012]


def test_issue_sort_uses_natural_order_in_both_directions(client):
    for issue in ("10", "2", "1A", "1"):
        add_comic(client, issue_number=issue)

    ascending = client.get(
        "/api/comics", params={"sort_by": "issue_number", "sort_order": "asc"}
    ).json()["items"]
    descending = client.get(
        "/api/comics", params={"sort_by": "issue_number", "sort_order": "desc"}
    ).json()["items"]
    assert [comic["issue_number"] for comic in ascending] == ["1", "1A", "2", "10"]
    assert [comic["issue_number"] for comic in descending] == ["10", "2", "1A", "1"]


def test_pagination_reports_totals_and_progressively_loads(client):
    for issue in ("1", "2", "3", "4", "5"):
        add_comic(client, issue_number=issue)

    first = client.get("/api/comics", params={"limit": 2, "offset": 0}).json()
    second = client.get("/api/comics", params={"limit": 2, "offset": 2}).json()
    last = client.get("/api/comics", params={"limit": 2, "offset": 4}).json()

    assert first["total"] == second["total"] == last["total"] == 5
    assert first["has_more"] is True
    assert second["has_more"] is True
    assert last["has_more"] is False
    assert len(first["items"]) == len(second["items"]) == 2
    assert len(last["items"]) == 1
    assert len(
        {comic["id"] for page in (first, second, last) for comic in page["items"]}
    ) == 5
    assert client.get("/api/comics", params={"limit": 101}).status_code == 422


def test_collection_summary_counts_active_entries_copies_and_known_cost(client):
    first = add_comic(
        client,
        series_title="Saga",
        issue_number="1",
        quantity=2,
        purchase_cost=3.5,
    )
    add_comic(
        client,
        series_title="Saga",
        issue_number="2",
        quantity=3,
        publisher="Image Comics",
        purchase_cost=None,
    )
    add_comic(
        client,
        series_title="Detective Comics",
        issue_number="1",
        publisher="DC Comics",
        quantity=4,
        purchase_cost=2,
    )

    summary = client.get("/api/collection/summary").json()
    assert summary == {
        "comic_count": 3,
        "total_copies": 9,
        "series_count": 2,
        "publisher_count": 2,
        "known_purchase_cost": 15,
    }

    client.delete(f"/api/comics/{first['id']}")
    active_summary = client.get("/api/collection/summary").json()
    assert active_summary["comic_count"] == 2
    assert active_summary["total_copies"] == 7
    assert active_summary["known_purchase_cost"] == 8
