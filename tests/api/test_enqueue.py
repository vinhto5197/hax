"""The API's shared Celery publisher: both hand-offs, the backlog cap, and
what a log line is allowed to carry.

No broker and no network — every task here is a recorder. `_pending` is
drained and asserted empty after each test, so no publish can run against a
real task once its monkeypatch is undone.
"""

import asyncio
import logging
import threading
from types import SimpleNamespace

import pytest

from apps.api import enqueue

_retry_flags: list[bool] = []


def fake_task(name: str, fn):
    """A stand-in Celery task whose apply_async records the retry flag and
    calls `fn` with the payload."""

    def apply_async(args, retry):
        _retry_flags.append(retry)
        return fn(*args)

    return SimpleNamespace(name=name, apply_async=apply_async)


@pytest.fixture(autouse=True)
async def no_publish_outlives_its_test():
    _retry_flags.clear()
    yield
    await asyncio.gather(*enqueue._pending, return_exceptions=True)
    # gather returns when the tasks are done; the done-callback that discards
    # them is scheduled via call_soon and needs one more loop iteration.
    await asyncio.sleep(0)
    assert enqueue._pending == set()
    # A dead broker must fail fast: the publish is never retried in-process.
    assert all(flag is False for flag in _retry_flags)


async def test_fire_and_forget_returns_before_a_stuck_publish_finishes():
    started, release = threading.Event(), threading.Event()
    threads: list[str] = []

    def stuck(conversation_id: str, user_id: str) -> None:
        threads.append(threading.current_thread().name)
        started.set()
        release.wait(timeout=30)

    task = fake_task("generate_title", stuck)
    try:
        enqueue.fire_and_forget(task, "cid", "uid", log_ref="cid")
        # The default executor (password hashing, storage I/O) still serves
        # while the publish is stuck on its own pool.
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5), 10) is True
        assert len(enqueue._pending) == 1
        assert threads[0].startswith("enqueue")
    finally:
        release.set()


async def test_a_full_backlog_drops_the_publish_and_logs_the_ref_only(
    monkeypatch, caplog
):
    release = threading.Event()
    published: list[str] = []

    def stuck(to: str, template: str, params: dict) -> None:
        release.wait(timeout=30)
        published.append(to)

    task = fake_task("send_email", stuck)
    monkeypatch.setattr(enqueue, "MAX_PENDING", 1)
    caplog.set_level(logging.WARNING)
    try:
        enqueue.fire_and_forget(
            task, "first@example.com", "verify_email", {}, log_ref="verify_email"
        )
        enqueue.fire_and_forget(
            task, "dropped@example.com", "verify_email", {}, log_ref="verify_email"
        )
    finally:
        release.set()
    await asyncio.gather(*enqueue._pending)

    assert published == ["first@example.com"]
    assert "backlog full" in caplog.text
    assert "send_email" in caplog.text and "verify_email" in caplog.text
    # Arg 0 is an address here: the line names the task and the caller's ref,
    # never the payload.
    assert "dropped@example.com" not in caplog.text


async def test_a_failed_publish_is_logged_by_type_and_never_raised(caplog):
    def boom(to: str, template: str, params: dict) -> None:
        raise OSError("relay://user:pw@host")

    caplog.set_level(logging.WARNING)
    enqueue.fire_and_forget(
        fake_task("send_email", boom),
        "user@example.com",
        "verify_email",
        {},
        log_ref="verify_email",
    )
    await asyncio.gather(*enqueue._pending)

    assert "OSError" in caplog.text and "verify_email" in caplog.text
    assert "user@example.com" not in caplog.text and "relay://" not in caplog.text


async def test_publish_awaits_the_broker_and_never_retries_in_process():
    calls: list[tuple] = []
    task = fake_task("ingest_document", lambda *args: calls.append(args))

    await enqueue.publish(task, "doc-id", "user-id")

    assert calls == [("doc-id", "user-id")]
    assert _retry_flags == [False]


async def test_publish_raises_what_the_broker_raised():
    def boom(document_id: str, user_id: str) -> None:
        raise OSError("broker down")

    with pytest.raises(OSError, match="broker down"):
        await enqueue.publish(fake_task("ingest_document", boom), "doc-id", "user-id")
