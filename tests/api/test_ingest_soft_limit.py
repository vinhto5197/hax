"""An ingest that hits Celery's soft time limit is failed, not retried: a
document too slow to finish once would be just as slow on every retry, and a
retry would hold the single ingest slot again. The hard limit stays above
the soft one so the task gets to record the failure before it is killed.
Runs the real task body with a pushed request, the pipeline stubbed, through
the APP engine."""

import asyncio

import pytest
from celery.exceptions import Retry, SoftTimeLimitExceeded
from sqlalchemy import text

import apps.worker.tasks as tasks
from apps.worker.celery_app import celery_app
from packages.db import engine as app_engine
from tests.api.factories import make_document


async def _status(admin_engine, doc_id):
    async with admin_engine.connect() as conn:
        return await conn.scalar(
            text("SELECT status FROM documents WHERE id = :i"), {"i": doc_id}
        )


@pytest.mark.parametrize("start", ["processing", "pending"])
async def test_soft_time_limit_fails_the_document_without_a_retry(
    admin_engine, user_a, monkeypatch, start
):
    doc = await make_document(
        admin_engine, user_a.id, status=start, storage_key="documents/x/a.txt"
    )

    async def too_slow(doc_id):
        raise SoftTimeLimitExceeded()

    retries = []

    def record_retry(*args, **kwargs):
        retries.append((args, kwargs))
        raise AssertionError("a soft time limit must not be retried")

    monkeypatch.setattr(tasks, "ingest_document_async", too_slow)
    monkeypatch.setattr(tasks.ingest_document, "retry", record_retry)

    def run():
        task = tasks.ingest_document
        task.push_request(id="t", retries=0)
        try:
            task.run(str(doc), str(user_a.id))
        finally:
            task.pop_request()

    await app_engine.dispose()
    try:
        await asyncio.to_thread(run)
    except Retry:
        pytest.fail("the task asked Celery for a retry")
    except AssertionError:
        raise
    except Exception:
        # Re-raising the time-limit error (or a permanent one) is fine; only
        # a retry is wrong.
        pass

    assert retries == []
    assert await _status(admin_engine, doc) == "failed"


def test_soft_time_limit_is_set_below_the_hard_limit():
    conf = celery_app.conf
    assert conf.task_soft_time_limit is not None
    assert conf.task_time_limit is not None
    assert conf.task_soft_time_limit < conf.task_time_limit
