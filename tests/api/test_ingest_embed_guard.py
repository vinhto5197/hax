"""Failures that retrying cannot fix end the ingest at once: text with a NUL
character is refused before anything is embedded, and an embedder that
raises a ValueError or returns the wrong number of vectors is permanent. The
stored error is the pipeline's static message, never the embedder's text.
Runs the real task the way tests/api/test_ingest_status.py does."""

import asyncio

import pytest

import apps.worker.tasks as tasks
from packages.core import storage
from packages.core.rag import ingest
from packages.core.rag.errors import PermanentIngestError
from packages.db import engine as app_engine
from tests.api.factories import make_document
from tests.api.test_ingest_status import _row, unit_vec


async def _fails_without_retry(admin_engine, user, monkeypatch, raw, embed):
    doc = await make_document(
        admin_engine,
        user.id,
        filename="a.txt",
        status="pending",
        storage_key="documents/x/a.txt",
    )
    monkeypatch.setattr(storage, "get", lambda key: raw)
    monkeypatch.setattr(ingest, "embed_documents", embed)
    retries = []
    monkeypatch.setattr(
        tasks.ingest_document, "retry", lambda *a, **k: retries.append(a)
    )

    def run():
        task = tasks.ingest_document
        task.push_request(id="t", retries=0)
        try:
            task.run(str(doc), str(user.id))
        finally:
            task.pop_request()

    await app_engine.dispose()
    with pytest.raises(PermanentIngestError):
        await asyncio.to_thread(run)

    status, error, chunks = await _row(admin_engine, doc)
    assert (status, chunks, retries) == ("failed", 0, [])
    return error


async def test_text_with_nul_fails_before_embedding(admin_engine, user_a, monkeypatch):
    embedded = []

    async def embed(chunks):
        embedded.append(chunks)
        return [unit_vec(0) for _ in chunks]

    error = await _fails_without_retry(
        admin_engine, user_a, monkeypatch, b"alpha secret\x00 beta " * 40, embed
    )
    assert "nul" in error.lower()
    assert "secret" not in error
    assert embedded == []


async def _raises(chunks):
    raise ValueError("bad shape")


async def _one_short(chunks):
    return [unit_vec(0) for _ in chunks[1:]]


@pytest.mark.parametrize("embed", [_raises, _one_short])
async def test_a_malformed_embedding_is_permanent(
    admin_engine, user_a, monkeypatch, embed
):
    # Long enough for several chunks, so "one short" is a count mismatch.
    error = await _fails_without_retry(
        admin_engine, user_a, monkeypatch, b"alpha secret " * 400, embed
    )
    assert error
    assert "bad shape" not in error
