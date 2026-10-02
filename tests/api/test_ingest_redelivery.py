"""A restored (redelivered) ingest message simply runs again — ingestion is
idempotent — and a lost worker's message is not requeued. Runs the real task
body with a pushed request, the pipeline stubbed, through the APP engine."""

import asyncio

import pytest

import apps.worker.tasks as tasks
from apps.worker.celery_app import celery_app
from packages.db import engine as app_engine
from tests.api.factories import make_document


@pytest.fixture
def pipeline(monkeypatch):
    calls: list = []

    async def fake(doc_id):
        calls.append(doc_id)

    monkeypatch.setattr(tasks, "ingest_document_async", fake)
    return calls


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


async def test_a_redelivered_message_runs_like_any_other(
    admin_engine, user_a, pipeline
):
    doc = await make_document(admin_engine, user_a.id, status="processing")
    await _deliver(doc, user_a.id, redelivered=True)
    assert pipeline == [doc]


def test_a_lost_worker_does_not_requeue_and_orphans_return_in_minutes():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is False
    assert celery_app.conf.broker_transport_options["visibility_timeout"] == 600
