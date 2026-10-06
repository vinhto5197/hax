"""A signed-in user gets UPLOADS_PER_HOUR and UPLOADS_PER_DAY accepted uploads,
counted per user in Redis. Only an accepted upload spends a slot; a refused
one is a 429 with a string detail and leaves no document row."""

from types import SimpleNamespace

import pytest

import apps.api.routers.documents as documents_router
from tests.api.conftest import bearer

LIMIT_DETAIL = "upload limit reached; try again later"


@pytest.fixture
def stub_publish(monkeypatch):
    from packages.core import storage

    monkeypatch.setattr(storage, "put", lambda key, content, mime: None)
    monkeypatch.setattr(
        documents_router,
        "ingest_document",
        SimpleNamespace(name="ingest_document", apply_async=lambda args, retry: None),
    )


def _upload(client, user, name="mine.txt", content=b"hello world"):
    return client.post(
        "/api/documents",
        files={"file": (name, content, "text/plain")},
        headers=bearer(user),
    )


async def test_hour_cap_refuses_the_next_upload_per_user(
    client, user_a, user_b, stub_publish, monkeypatch
):
    monkeypatch.setattr(documents_router, "UPLOADS_PER_HOUR", 2)
    for i in range(2):
        assert (await _upload(client, user_a, f"a{i}.txt")).status_code == 200
    r = await _upload(client, user_a, "a2.txt")
    assert r.status_code == 429
    assert r.json()["detail"] == LIMIT_DETAIL
    # Buckets are per user: user_b is untouched by user_a's spend.
    assert (await _upload(client, user_b, "b0.txt")).status_code == 200


async def test_rejected_upload_does_not_spend_a_slot(
    client, user_a, stub_publish, monkeypatch
):
    monkeypatch.setattr(documents_router, "UPLOADS_PER_HOUR", 1)
    r = await _upload(client, user_a, "tool.exe", b"MZ")
    assert r.status_code == 400
    assert (await _upload(client, user_a, "ok.txt")).status_code == 200


async def test_day_cap_is_independent_of_the_hour_cap(
    client, user_a, stub_publish, monkeypatch
):
    monkeypatch.setattr(documents_router, "UPLOADS_PER_HOUR", 10)
    monkeypatch.setattr(documents_router, "UPLOADS_PER_DAY", 1)
    assert (await _upload(client, user_a, "a0.txt")).status_code == 200
    r = await _upload(client, user_a, "a1.txt")
    assert r.status_code == 429
    assert r.json()["detail"] == LIMIT_DETAIL


async def test_refused_upload_creates_no_document_row(
    client, user_a, stub_publish, monkeypatch
):
    monkeypatch.setattr(documents_router, "UPLOADS_PER_HOUR", 1)
    accepted = await _upload(client, user_a, "a0.txt")
    assert accepted.status_code == 200
    assert (await _upload(client, user_a, "a1.txt")).status_code == 429
    listing = await client.get("/api/documents", headers=bearer(user_a))
    assert [d["id"] for d in listing.json()] == [accepted.json()["id"]]
