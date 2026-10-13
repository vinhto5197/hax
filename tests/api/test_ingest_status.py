"""'failed' is terminal for the worker: the claim at the start of an ingest
and the 'ready' write at its end are both conditional on the row still being
in flight, so a row the API's deadline has failed is never resurrected by
the late attempt. Runs the real pipeline against the APP engine with storage
and the embedder stubbed, the way tests/api/test_authz_pipeline.py does."""

import asyncio

import pytest
from sqlalchemy import text

import apps.worker.tasks as tasks
from packages.core import storage
from packages.core.rag import ingest
from packages.core.rag.errors import PermanentIngestError
from packages.db import engine as app_engine
from packages.db.user_context import current_user_id
from tests.api.factories import make_document

DIM = 1024
DEADLINE_ERROR = "processing did not finish; upload the file again"


def unit_vec(hot: int) -> list[float]:
    v = [0.0] * DIM
    v[hot] = 1.0
    return v


async def _row(admin_engine, doc_id):
    async with admin_engine.connect() as conn:
        status, error = (
            await conn.execute(
                text("SELECT status, error FROM documents WHERE id = :i"),
                {"i": doc_id},
            )
        ).one()
        chunks = await conn.scalar(
            text("SELECT count(*) FROM chunks WHERE document_id = :i"), {"i": doc_id}
        )
    return status, error, chunks


async def test_a_failed_row_is_not_claimed_and_keeps_its_error(
    admin_engine, user_a, monkeypatch
):
    # Through the task, so its own terminal write (mark_document_failed) is
    # proven not to overwrite the deadline's message either.
    doc = await make_document(
        admin_engine, user_a.id, status="failed", storage_key="documents/x/a.md"
    )
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE documents SET error = :e WHERE id = :i"),
            {"e": DEADLINE_ERROR, "i": doc},
        )
    fetched = []
    monkeypatch.setattr(storage, "get", lambda key: fetched.append(key) or b"x")

    def run():
        task = tasks.ingest_document
        task.push_request(id="t", retries=0)
        try:
            task.run(str(doc), str(user_a.id))
        finally:
            task.pop_request()

    await app_engine.dispose()
    with pytest.raises(PermanentIngestError, match="not in flight"):
        await asyncio.to_thread(run)

    assert fetched == []
    assert await _row(admin_engine, doc) == ("failed", DEADLINE_ERROR, 0)


async def test_a_row_failed_mid_ingest_stays_failed_with_no_chunks(
    admin_engine, user_a, monkeypatch
):
    # The deadline fires while the embeddings are being computed: the 'ready'
    # write matches no row, the attempt raises, and the transaction holding
    # the chunk set rolls back with it.
    doc = await make_document(
        admin_engine, user_a.id, status="pending", storage_key="documents/x/a.md"
    )
    monkeypatch.setattr(storage, "get", lambda key: b"alpha secret " * 40)

    async def embed_then_fail(chunks):
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE documents SET status = 'failed', error = :e WHERE id = :i"
                ),
                {"e": DEADLINE_ERROR, "i": doc},
            )
        return [unit_vec(0) for _ in chunks]

    monkeypatch.setattr(ingest, "embed_documents", embed_then_fail)

    token = current_user_id.set(user_a.id)
    try:
        with pytest.raises(PermanentIngestError) as excinfo:
            await ingest.ingest_document_async(doc)
    finally:
        current_user_id.reset(token)

    assert str(excinfo.value) == "document left processing during ingestion"
    assert await _row(admin_engine, doc) == ("failed", DEADLINE_ERROR, 0)


async def test_a_redelivered_message_after_ready_changes_nothing(
    admin_engine, user_a, monkeypatch
):
    # The work committed but the ack was lost: the restored message finds
    # 'ready' and returns without a claim, a fetch, or a second embed.
    doc = await make_document(
        admin_engine, user_a.id, status="ready", storage_key="documents/x/a.md"
    )
    fetched = []
    monkeypatch.setattr(storage, "get", lambda key: fetched.append(key) or b"x")

    token = current_user_id.set(user_a.id)
    try:
        await ingest.ingest_document_async(doc)
    finally:
        current_user_id.reset(token)

    assert fetched == []
    assert await _row(admin_engine, doc) == ("ready", None, 0)


async def test_a_late_failure_cannot_fail_a_ready_row(admin_engine, user_a):
    # A second attempt that loses to the first must not undo its result.
    doc = await make_document(
        admin_engine, user_a.id, status="ready", storage_key="documents/x/a.md"
    )
    token = current_user_id.set(user_a.id)
    try:
        await ingest.mark_document_failed(doc, "late attempt")
    finally:
        current_user_id.reset(token)

    assert (await _row(admin_engine, doc))[:2] == ("ready", None)
