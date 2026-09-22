"""The chat path's title triggers: one enqueue when a conversation is created,
one more per persisted assistant turn while the title is still NULL, never
before the commit and never fatal.

Drives the service functions directly with identity announced exactly as a
request announces it (RLS is on for the app engine); seeds and asserts go
through admin_engine. `generate_title.apply_async` is always replaced by a
recorder — no broker, no network. The publisher's own behaviour (pool,
backlog cap, retry flag) lives in tests/api/test_enqueue.py.
"""

import asyncio
import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text

import apps.api.chat_service as chat_service
from apps.api import enqueue
from packages.db import engine as app_engine
from packages.db.user_context import current_user_id
from tests.api.factories import make_conversation, make_message

PROMPT = "plan a trip to hanoi"


def _publisher(monkeypatch, fn):
    """Replace the task with a recorder taking the payload tuple."""

    def apply_async(args, retry):
        fn(*args)

    monkeypatch.setattr(
        chat_service,
        "generate_title",
        SimpleNamespace(name="generate_title", apply_async=apply_async),
    )


@pytest.fixture(autouse=True)
async def no_enqueue_outlives_its_test():
    # A leaked publish would run after monkeypatch is undone, i.e. against the
    # real task and a real broker connection.
    yield
    await asyncio.gather(*enqueue._pending, return_exceptions=True)
    # gather returns when the tasks are done; the done-callback that discards
    # them is scheduled via call_soon and needs one more loop iteration.
    await asyncio.sleep(0)
    assert enqueue._pending == set()


@pytest.fixture
def enqueued(monkeypatch):
    calls: list[tuple[str, str]] = []
    _publisher(monkeypatch, lambda *payload: calls.append(payload))
    return calls


async def _as(user, coro):
    """Run a service call as `user`, then let its fire-and-forget enqueue
    finish so the recorder can be asserted on."""
    token = current_user_id.set(user.id)
    try:
        result = await coro
    finally:
        current_user_id.reset(token)
    await asyncio.gather(*enqueue._pending)
    return result


async def _messages(admin_engine, conv_id):
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT role, content FROM messages WHERE conversation_id = :i"
                " ORDER BY created_at, id"
            ),
            {"i": conv_id},
        )
        return [(role, content) for role, content in rows]


async def _counts(admin_engine, conv_id):
    async with admin_engine.connect() as conn:
        conversations = await conn.scalar(
            text("SELECT count(*) FROM conversations WHERE id = :i"), {"i": conv_id}
        )
        messages = await conn.scalar(
            text("SELECT count(*) FROM messages WHERE conversation_id = :i"),
            {"i": conv_id},
        )
    return conversations, messages


async def test_new_conversation_enqueues_once_with_the_committed_turn(
    admin_engine, user_a, monkeypatch
):
    # The recorder runs on the publisher thread, so it opens its own connection
    # on the NullPool admin engine and sees only committed rows.
    seen: list[tuple[str, str, tuple[int, int]]] = []

    def record(conversation_id: str, user_id: str) -> None:
        committed = asyncio.run(_counts(admin_engine, uuid.UUID(conversation_id)))
        seen.append((conversation_id, user_id, committed))

    _publisher(monkeypatch, record)
    conv_id = await _as(user_a, chat_service.persist_user_turn(PROMPT, None, user_a.id))
    assert seen == [(str(conv_id), str(user_a.id), (1, 1))]


async def test_enqueue_happens_after_the_commit(
    admin_engine, user_a, enqueued, monkeypatch
):
    # The publish is fire-and-forget, so ordering is asserted at the call:
    # until the commit the session still has a pooled connection checked out.
    checked_out: list[int] = []
    real = chat_service._enqueue_title

    def spy(conversation_id, user_id):
        checked_out.append(app_engine.pool.checkedout())
        real(conversation_id, user_id)

    monkeypatch.setattr(chat_service, "_enqueue_title", spy)
    conv_id = await _as(user_a, chat_service.persist_user_turn(PROMPT, None, user_a.id))
    await _as(
        user_a, chat_service.persist_assistant_turn(conv_id, user_a.id, "the answer")
    )
    assert checked_out == [0, 0]


async def test_existing_conversation_does_not_enqueue(admin_engine, user_a, enqueued):
    conv = await make_conversation(admin_engine, user_a.id)
    await _as(user_a, chat_service.persist_user_turn(PROMPT, conv, user_a.id))
    assert enqueued == []
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]


async def test_assistant_turn_re_enqueues_while_untitled(
    admin_engine, user_a, enqueued
):
    conv = await make_conversation(admin_engine, user_a.id)
    await _as(
        user_a, chat_service.persist_assistant_turn(conv, user_a.id, "the answer")
    )
    assert await _messages(admin_engine, conv) == [("assistant", "the answer")]
    assert enqueued == [(str(conv), str(user_a.id))]


async def test_assistant_turn_on_a_titled_conversation_does_not_enqueue(
    admin_engine, user_a, enqueued
):
    conv = await make_conversation(admin_engine, user_a.id, title="Trip Planning")
    await _as(
        user_a, chat_service.persist_assistant_turn(conv, user_a.id, "the answer")
    )
    assert await _messages(admin_engine, conv) == [("assistant", "the answer")]
    assert enqueued == []


async def test_assistant_turn_without_content_persists_nothing_and_enqueues_nothing(
    admin_engine, user_a, enqueued
):
    conv = await make_conversation(admin_engine, user_a.id)
    await _as(user_a, chat_service.persist_assistant_turn(conv, user_a.id, ""))
    assert await _messages(admin_engine, conv) == []
    assert enqueued == []


async def test_enqueue_failure_on_the_user_turn_is_not_fatal(
    admin_engine, user_a, monkeypatch, caplog
):
    def boom(conversation_id: str, user_id: str) -> None:
        raise OSError(PROMPT)

    _publisher(monkeypatch, boom)
    caplog.set_level(logging.WARNING)

    conv_id = await _as(user_a, chat_service.persist_user_turn(PROMPT, None, user_a.id))

    assert await _messages(admin_engine, conv_id) == [("user", PROMPT)]
    assert "OSError" in caplog.text and str(conv_id) in caplog.text
    assert PROMPT not in caplog.text


async def test_enqueue_failure_on_the_assistant_turn_is_not_fatal(
    admin_engine, user_a, monkeypatch, caplog
):
    def boom(conversation_id: str, user_id: str) -> None:
        raise OSError("the answer")

    _publisher(monkeypatch, boom)
    caplog.set_level(logging.WARNING)
    conv = await make_conversation(admin_engine, user_a.id)

    await _as(
        user_a, chat_service.persist_assistant_turn(conv, user_a.id, "the answer")
    )

    assert await _messages(admin_engine, conv) == [("assistant", "the answer")]
    assert "OSError" in caplog.text and str(conv) in caplog.text
    assert "the answer" not in caplog.text


async def test_event_stream_forwards_the_user_id(admin_engine, user_a, enqueued):
    conv = await make_conversation(admin_engine, user_a.id)

    async def stream_fn(messages):
        yield "he"
        yield "llo"

    token = current_user_id.set(user_a.id)
    try:
        chunks = [
            chunk
            async for chunk in chat_service.event_stream(stream_fn, [], conv, user_a.id)
        ]
    finally:
        current_user_id.reset(token)
    await asyncio.gather(*enqueue._pending)

    assert "[DONE]" in chunks[-1]
    assert await _messages(admin_engine, conv) == [("assistant", "hello")]
    assert enqueued == [(str(conv), str(user_a.id))]


async def test_foreign_conversation_404s_and_enqueues_nothing(
    admin_engine, user_a, user_b, enqueued
):
    conv = await make_conversation(admin_engine, user_a.id)
    await make_message(admin_engine, conv, "user", "a's question")

    with pytest.raises(HTTPException) as excinfo:
        await _as(user_b, chat_service.persist_user_turn(PROMPT, conv, user_b.id))

    assert excinfo.value.status_code == 404
    assert enqueued == []
    assert await _messages(admin_engine, conv) == [("user", "a's question")]
