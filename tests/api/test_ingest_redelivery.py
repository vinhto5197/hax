"""A message that already killed a worker comes back redelivered, and is
never parsed again: the document is recorded failed with a message that
says to upload again. Runs the real task body with a pushed request, the
pipeline stubbed, through the APP engine."""

import asyncio

import pytest
from sqlalchemy import text

import apps.worker.tasks as tasks
from packages.db import engine as app_engine
from tests.api.factories import make_document


@pytest.fixture
def pipeline(monkeypatch):
    calls: list = []

    async def fake(doc_id):
        calls.append(doc_id)

    monkeypatch.setattr(tasks, "ingest_document_async", fake)
    return calls


async def _status(admin_engine, doc_id):
    async with admin_engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT status, error FROM documents WHERE id = :i"), {"i": doc_id}
            )
        ).one()


async def _deliver(doc_id, user_id, *, redelivered: bool):
    def run():
        task = tasks.ingest_document
        task.push_request(id="t", retries=0, delivery_info={"redelivered": redelivered})
        try:
            task.run(str(doc_id), str(user_id))
        finally:
            task.pop_request()

    await app_engine.dispose()
    await asyncio.to_thread(run)


async def test_a_first_delivery_is_processed(admin_engine, user_a, pipeline):
    doc = await make_document(admin_engine, user_a.id, status="processing")
    await _deliver(doc, user_a.id, redelivered=False)
    assert pipeline == [doc]
    assert (await _status(admin_engine, doc)).status == "processing"


async def test_a_redelivery_records_failed_without_parsing(
    admin_engine, user_a, pipeline
):
    doc = await make_document(admin_engine, user_a.id, status="processing")
    await _deliver(doc, user_a.id, redelivered=True)
    assert pipeline == []
    status, error = await _status(admin_engine, doc)
    assert status == "failed"
    assert error == tasks.INTERRUPTED_ERROR
