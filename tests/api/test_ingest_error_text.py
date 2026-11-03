"""A failed ingest's stored `error` (shown in the documents list) never echoes
the document's storage key, filename or id — a missing object or a missing
storage key fails the row with a static message. Runs the real task body
with a pushed request, through the APP engine, storage stubbed."""

import asyncio

import pytest
from sqlalchemy import text

import apps.worker.tasks as tasks
from packages.core import storage
from packages.core.rag.errors import PermanentIngestError
from packages.db import engine as app_engine
from tests.api.factories import make_document

FILENAME = "secret-plan-7f3a.txt"


async def _run_task(doc_id, user_id):
    def run():
        task = tasks.ingest_document
        task.push_request(id="t", retries=0)
        try:
            task.run(str(doc_id), str(user_id))
        finally:
            task.pop_request()

    await app_engine.dispose()
    with pytest.raises(PermanentIngestError):
        await asyncio.to_thread(run)


async def _row(admin_engine, doc_id):
    async with admin_engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT status, error FROM documents WHERE id = :i"),
                {"i": doc_id},
            )
        ).one()


def _assert_scrubbed(status, error, doc_id, key):
    assert status == "failed"
    assert error
    for secret in (key, FILENAME, str(doc_id)):
        if secret:
            assert secret not in error


async def test_a_missing_object_fails_without_leaking_the_key(
    admin_engine, user_a, monkeypatch
):
    doc = await make_document(
        admin_engine, user_a.id, filename=FILENAME, status="pending"
    )
    key = f"documents/{doc}/{FILENAME}"
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE documents SET storage_key = :k WHERE id = :i"),
            {"k": key, "i": doc},
        )

    def missing(k):
        raise storage.StorageKeyNotFound(k)

    monkeypatch.setattr(storage, "get", missing)

    await _run_task(doc, user_a.id)
    _assert_scrubbed(*await _row(admin_engine, doc), doc, key)


async def test_a_row_without_a_storage_key_fails_without_leaking_ids(
    admin_engine, user_a, monkeypatch
):
    doc = await make_document(
        admin_engine, user_a.id, filename=FILENAME, status="pending", storage_key=None
    )
    monkeypatch.setattr(storage, "get", lambda k: b"never fetched")

    await _run_task(doc, user_a.id)
    _assert_scrubbed(*await _row(admin_engine, doc), doc, f"documents/{doc}/{FILENAME}")
