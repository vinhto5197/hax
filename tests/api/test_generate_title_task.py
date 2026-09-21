"""generate_title end to end minus the network: identity announcement, the
no-connection-across-the-model-call shape, first-writer-wins, retry policy.

Runs through the APP engine (hax_app, RLS on) with identity announced exactly
as the task contract announces it; seeds and asserts go through admin_engine.
The titler is always faked — no test may reach the network."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest
from celery.exceptions import Retry
from sqlalchemy import text

import apps.worker.tasks as tasks
from packages.db import engine as app_engine
from packages.db.user_context import current_user_id
from tests.api.factories import make_conversation, make_message

CONV_ID = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000002"


async def _title(admin_engine, conv_id):
    async with admin_engine.connect() as conn:
        row = await conn.execute(
            text("SELECT title FROM conversations WHERE id = :i"), {"i": conv_id}
        )
        return row.scalar_one()


@pytest.fixture
def titler(monkeypatch):
    fake = AsyncMock(return_value="Trip Planning Notes")
    monkeypatch.setattr(tasks.titles, "suggest_title", fake)
    return fake


async def _seed(admin_engine, user):
    conv = await make_conversation(admin_engine, user.id)
    await make_message(admin_engine, conv, "user", "plan a trip to hanoi")
    return conv


async def _announced(user, coro):
    token = current_user_id.set(user.id)
    try:
        await coro
    finally:
        current_user_id.reset(token)


async def test_writes_a_title_for_the_owner(admin_engine, user_a, titler):
    conv = await _seed(admin_engine, user_a)
    await _announced(user_a, tasks.generate_title_async(conv, user_a.id))
    assert await _title(admin_engine, conv) == "Trip Planning Notes"
    titler.assert_awaited_once_with("plan a trip to hanoi")


async def test_no_connection_is_held_across_the_model_call(
    admin_engine, user_a, titler
):
    conv = await _seed(admin_engine, user_a)
    checked_out = []

    async def spy(message):
        checked_out.append(app_engine.pool.checkedout())
        return "Trip Planning Notes"

    titler.side_effect = spy
    await _announced(user_a, tasks.generate_title_async(conv, user_a.id))
    # A slow model must never pin a pooled connection: the read session is
    # closed before suggest_title runs, the write session opened after.
    assert checked_out == [0]


async def test_skips_the_model_when_already_titled(admin_engine, user_a, titler):
    conv = await make_conversation(admin_engine, user_a.id, title="Existing")
    await make_message(admin_engine, conv, "user", "hi")
    await _announced(user_a, tasks.generate_title_async(conv, user_a.id))
    titler.assert_not_awaited()
    assert await _title(admin_engine, conv) == "Existing"


async def test_conversation_without_a_user_message_skips_the_model(
    admin_engine, user_a, titler
):
    conv = await make_conversation(admin_engine, user_a.id)
    await make_message(admin_engine, conv, "assistant", "opening note")
    await _announced(user_a, tasks.generate_title_async(conv, user_a.id))
    titler.assert_not_awaited()
    assert await _title(admin_engine, conv) is None


async def test_foreign_user_id_writes_nothing(admin_engine, user_a, user_b, titler):
    conv = await _seed(admin_engine, user_a)
    await _announced(user_b, tasks.generate_title_async(conv, user_b.id))
    titler.assert_not_awaited()
    assert await _title(admin_engine, conv) is None


async def test_no_title_from_the_model_leaves_null(admin_engine, user_a, titler):
    titler.return_value = None
    conv = await _seed(admin_engine, user_a)
    await _announced(user_a, tasks.generate_title_async(conv, user_a.id))
    assert await _title(admin_engine, conv) is None


async def test_a_second_run_leaves_the_first_title(admin_engine, user_a, titler):
    conv = await _seed(admin_engine, user_a)
    await _announced(user_a, tasks.generate_title_async(conv, user_a.id))
    titler.return_value = "Second Attempt"
    await _announced(user_a, tasks.generate_title_async(conv, user_a.id))
    assert await _title(admin_engine, conv) == "Trip Planning Notes"


async def _apply_for_real(conv, user):
    """The real task, real _run_async. Off-thread because the task drives its
    own event loop; the app pool is emptied first so that loop never inherits
    a connection bound to the test's loop."""
    await app_engine.dispose()
    return await asyncio.to_thread(
        lambda: tasks.generate_title.apply(args=(str(conv), str(user.id)))
    )


async def test_the_task_announces_the_payload_identity_and_writes(
    admin_engine, user_a, titler, caplog
):
    caplog.set_level(logging.INFO)
    conv = await _seed(admin_engine, user_a)
    result = await _apply_for_real(conv, user_a)
    assert result.successful()
    # Nothing announced here: the identity that satisfied RLS came from the
    # payload, and the ids reached the coroutine in the right order.
    assert await _title(admin_engine, conv) == "Trip Planning Notes"
    assert current_user_id.get() is None
    assert str(conv) in caplog.text
    assert "hanoi" not in caplog.text and "Trip Planning" not in caplog.text


async def test_a_permanent_failure_logs_no_content(
    admin_engine, user_a, titler, caplog
):
    titler.side_effect = ValueError("plan a trip to hanoi")
    conv = await _seed(admin_engine, user_a)
    result = await _apply_for_real(conv, user_a)
    assert result.successful()
    assert "ValueError" in caplog.text and str(conv) in caplog.text
    assert "hanoi" not in caplog.text
    assert await _title(admin_engine, conv) is None


def _run_async_fake(exc=None):
    def run(coro):
        # -W error: _run_async normally consumes the coroutine; a bare mock
        # would leave it unawaited and the RuntimeWarning would fail the run.
        coro.close()
        if exc is not None:
            raise exc

    return MagicMock(side_effect=run)


def _run(monkeypatch, exc, retries=0):
    monkeypatch.setattr(tasks, "_run_async", _run_async_fake(exc))
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(tasks.generate_title, "retry", retry)
    return retry, tasks.generate_title.apply(args=(CONV_ID, USER_ID), retries=retries)


def _status_error(code):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIStatusError(
        "x", response=httpx.Response(code, request=req), body=None
    )


@pytest.mark.parametrize(
    "exc",
    [
        anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")),
        _status_error(429),
        _status_error(529),
        OSError("db down"),
    ],
)
def test_transient_errors_retry_with_backoff(monkeypatch, exc):
    retry, result = _run(monkeypatch, exc)
    assert retry.call_args.kwargs["countdown"] == 5  # base * 2**0
    assert result.state == "RETRY"


def test_client_errors_are_permanent(monkeypatch, caplog):
    retry, result = _run(monkeypatch, _status_error(400))
    retry.assert_not_called()
    # Logged and dropped: the title stays NULL and the next turn re-enqueues.
    assert result.successful()
    assert "400" in caplog.text


def test_gives_up_quietly_at_the_cap(monkeypatch, caplog):
    retry, result = _run(monkeypatch, OSError("db down"), retries=tasks.MAX_RETRIES)
    retry.assert_not_called()
    assert result.successful()
    assert "giving up" in caplog.text


def test_identity_is_reset_after_the_task(monkeypatch):
    monkeypatch.setattr(tasks, "_run_async", _run_async_fake())
    tasks.generate_title.apply(args=(CONV_ID, USER_ID))
    assert current_user_id.get() is None


def test_identity_is_reset_after_a_failed_task(monkeypatch):
    _run(monkeypatch, OSError("db down"))
    assert current_user_id.get() is None
