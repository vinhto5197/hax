"""Failures that retrying cannot fix end the ingest at once: text with a NUL
character is refused before anything is embedded, and an embedder that
raises a ValueError or returns the wrong number of vectors is a permanent
failure, not a transient one to retry. The stored error is the pipeline's own
static message, never the embedder's text. Runs the real task and pipeline
against the APP engine with storage and the embedder stubbed, the way
tests/api/test_ingest_status.py does."""

import asyncio

import pytest
from sqlalchemy import text

import apps.worker.tasks as tasks
from packages.core import storage
from packages.core.rag import ingest
from packages.core.rag.errors import PermanentIngestError
from packages.db import engine as app_engine
from tests.api.factories import make_document

DIM = 1024


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


@pytest.fixture
def retries(monkeypatch):
    calls = []

    def record_retry(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("a permanent failure must not be retried")

    monkeypatch.setattr(tasks.ingest_document, "retry", record_retry)
    return calls


async def _run_task(doc_id, user_id):
    def run():
        task = tasks.ingest_document
        task.push_request(id="t", retries=0)
        try:
            task.run(str(doc_id), str(user_id))
        finally:
            task.pop_request()

    await app_engine.dispose()
    await asyncio.to_thread(run)


async def _txt_document(admin_engine, user_id):
    return await make_document(
        admin_engine,
        user_id,
        filename="a.txt",
        status="pending",
        storage_key="documents/x/a.txt",
    )


async def test_text_with_nul_fails_before_embedding(
    admin_engine, user_a, monkeypatch, retries
):
    doc = await _txt_document(admin_engine, user_a.id)
    monkeypatch.setattr(storage, "get", lambda key: b"alpha secret\x00 beta " * 40)
    embedded = []

    async def embed(chunks):
        embedded.append(chunks)
        return [unit_vec(0) for _ in chunks]

    monkeypatch.setattr(ingest, "embed_documents", embed)

    with pytest.raises(PermanentIngestError):
        await _run_task(doc, user_a.id)

    status, error, chunks = await _row(admin_engine, doc)
    assert status == "failed"
    assert "nul" in error.lower()
    assert "secret" not in error
    assert chunks == 0
    assert embedded == []
    assert retries == []


async def test_embedder_value_error_is_permanent_and_not_echoed(
    admin_engine, user_a, monkeypatch, retries
):
    doc = await _txt_document(admin_engine, user_a.id)
    monkeypatch.setattr(storage, "get", lambda key: b"alpha secret " * 40)

    async def embed(chunks):
        raise ValueError("bad shape")

    monkeypatch.setattr(ingest, "embed_documents", embed)

    with pytest.raises(PermanentIngestError):
        await _run_task(doc, user_a.id)

    status, error, chunks = await _row(admin_engine, doc)
    assert status == "failed"
    assert error
    assert "bad shape" not in error
    assert chunks == 0
    assert retries == []


async def test_embedder_returning_too_few_vectors_is_permanent(
    admin_engine, user_a, monkeypatch, retries
):
    doc = await _txt_document(admin_engine, user_a.id)
    # ~5200 characters: several chunks at the splitter's size, so "one fewer"
    # still leaves at least one vector and is a count mismatch, not an empty.
    monkeypatch.setattr(storage, "get", lambda key: b"alpha secret " * 400)
    seen = []

    async def embed(chunks):
        seen.append(len(chunks))
        return [unit_vec(0) for _ in chunks[1:]]

    monkeypatch.setattr(ingest, "embed_documents", embed)

    with pytest.raises(PermanentIngestError):
        await _run_task(doc, user_a.id)

    assert sum(seen) >= 2
    status, error, chunks = await _row(admin_engine, doc)
    assert status == "failed"
    assert error
    assert chunks == 0
    assert retries == []
