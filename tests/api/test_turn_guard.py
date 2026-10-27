"""One reply in flight per conversation: a turn claims
`conversations.streaming_since` with its user message, the reply's save
clears it, a claim older than the window counts as free, and a second turn
meanwhile is a 409 that persists nothing. Ownership still answers first: a
foreign conversation is a 404 and leaves the owner's claim alone.

Service calls run with identity announced as a request announces it (RLS is
on for the app engine); seeds, clock moves and asserts go through
admin_engine. Publishes land in conftest's `published` recorder — no broker.
"""

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text

import apps.api.chat_service as chat_service
import apps.api.routers.chat as chat_router
from apps.api import enqueue
from packages.db.repos import conversations as conversations_repo
from packages.db.session import AsyncSessionLocal
from packages.db.user_context import current_user_id
from tests.api.conftest import bearer
from tests.api.factories import make_conversation

PROMPT = "what did I upload?"
BUSY = 409
REPLY_FAILED = 'data: {"error": "reply_failed"}\n\n'


@pytest.fixture(autouse=True)
async def no_enqueue_outlives_its_test():
    yield
    await asyncio.gather(*enqueue._pending, return_exceptions=True)
    await asyncio.sleep(0)


@contextlib.contextmanager
def _identity(user):
    token = current_user_id.set(user.id)
    try:
        yield
    finally:
        current_user_id.reset(token)


async def _turn(user, conv):
    """A user turn as `user`; returns (conversation_id, claimed_at)."""
    with _identity(user):
        return await chat_service.persist_user_turn(PROMPT, conv, user.id)


async def _refused(user, conv) -> int:
    with pytest.raises(HTTPException) as excinfo:
        await _turn(user, conv)
    if excinfo.value.status_code == BUSY:
        assert excinfo.value.detail == chat_service.TURN_IN_PROGRESS
    return excinfo.value.status_code


def _stream_of(*events, error: Exception | None = None):
    async def stream_fn(messages):
        for event in events:
            yield event
        if error is not None:
            raise error

    return stream_fn


async def _reply(user, conv, claimed_at, stream_fn) -> list[str]:
    """Consume a whole reply as `user`."""
    with _identity(user):
        return [
            frame
            async for frame in chat_service.event_stream(
                stream_fn, [], conv, user.id, claimed_at=claimed_at
            )
        ]


async def _streaming_since(admin_engine, conv):
    async with admin_engine.connect() as conn:
        return await conn.scalar(
            text("SELECT streaming_since FROM conversations WHERE id = :c"),
            {"c": conv},
        )


async def _age_claim(admin_engine, conv, seconds: int) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE conversations"
                " SET streaming_since = now() - make_interval(secs => :s)"
                " WHERE id = :c"
            ),
            {"c": conv, "s": seconds},
        )


async def _messages(admin_engine, conv):
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT role, content FROM messages WHERE conversation_id = :c"
                " ORDER BY created_at, id"
            ),
            {"c": conv},
        )
        return [(role, content) for role, content in rows]


async def test_second_turn_while_a_reply_is_in_flight_is_refused_and_persists_nothing(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)
    before = await _messages(admin_engine, conv)

    assert await _refused(user_a, conv) == BUSY
    assert await _messages(admin_engine, conv) == before == [("user", PROMPT)]


async def test_a_new_turn_succeeds_right_after_a_reply_finishes(admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    await _reply(user_a, conv, claimed_at, _stream_of({"content": "done"}))

    assert await _streaming_since(admin_engine, conv) is None
    await _turn(user_a, conv)


class _ModelDown(Exception):
    pass


async def test_the_reply_is_saved_and_the_conversation_freed_before_done_is_sent(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    with _identity(user_a):
        gen = chat_service.event_stream(
            _stream_of({"content": "done"}),
            [],
            conv,
            user_a.id,
            claimed_at=claimed_at,
        )
        async for frame in gen:
            if frame == "data: [DONE]\n\n":
                break
        else:
            pytest.fail("the stream ended without a [DONE] frame")

        assert await _streaming_since(admin_engine, conv) is None
        assert await _messages(admin_engine, conv) == [
            ("user", PROMPT),
            ("assistant", "done"),
        ]
        _, newer_claim = await chat_service.persist_user_turn(PROMPT, conv, user_a.id)
        await gen.aclose()

    roles = [role for role, _ in await _messages(admin_engine, conv)]
    assert roles.count("assistant") == 1
    assert await _streaming_since(admin_engine, conv) == newer_claim


async def test_a_failed_reply_frees_the_conversation_and_stores_nothing_before_reply_failed_is_sent(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    with _identity(user_a):
        gen = chat_service.event_stream(
            _stream_of({"content": "partial"}, error=_ModelDown()),
            [],
            conv,
            user_a.id,
            claimed_at=claimed_at,
        )
        async for frame in gen:
            if frame == REPLY_FAILED:
                break
        else:
            pytest.fail("the stream ended without a reply_failed frame")

        assert await _streaming_since(admin_engine, conv) is None
        assert await _messages(admin_engine, conv) == [("user", PROMPT)]
        await gen.aclose()


async def test_a_new_turn_succeeds_after_the_reply_stream_fails(admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    frames = await _reply(
        user_a,
        conv,
        claimed_at,
        _stream_of({"content": "partial"}, error=_ModelDown()),
    )

    assert frames[-1] == REPLY_FAILED
    assert "data: [DONE]\n\n" not in frames
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]
    assert await _streaming_since(admin_engine, conv) is None
    await _turn(user_a, conv)


async def test_client_disconnect_persists_the_partial_reply_and_frees_the_conversation(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    with _identity(user_a):
        gen = chat_service.event_stream(
            _stream_of({"content": "he"}, {"content": "llo"}),
            [],
            conv,
            user_a.id,
            claimed_at=claimed_at,
        )
        async for frame in gen:
            if "he" in frame:
                break
        await gen.aclose()

    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "he"),
    ]
    assert await _streaming_since(admin_engine, conv) is None
    await _turn(user_a, conv)


async def test_a_reply_that_streams_nothing_still_frees_the_conversation(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    await _reply(user_a, conv, claimed_at, _stream_of())

    assert await _streaming_since(admin_engine, conv) is None
    await _turn(user_a, conv)


async def test_foreign_conversation_is_404_not_409(admin_engine, user_a, user_b):
    conv = await make_conversation(admin_engine, user_a.id)

    assert await _refused(user_b, conv) == 404
    assert await _streaming_since(admin_engine, conv) is None
    assert await _messages(admin_engine, conv) == []


async def test_foreign_conversation_is_404_while_its_owner_has_a_reply_in_flight(
    admin_engine, user_a, user_b
):
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)
    owners_claim = await _streaming_since(admin_engine, conv)

    assert await _refused(user_b, conv) == 404
    assert await _streaming_since(admin_engine, conv) == owners_claim
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]


async def test_two_concurrent_turns_on_one_conversation_let_exactly_one_through(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    with _identity(user_a):
        results = await asyncio.gather(
            chat_service.persist_user_turn(PROMPT, conv, user_a.id),
            chat_service.persist_user_turn(PROMPT, conv, user_a.id),
            return_exceptions=True,
        )

    refused = [r for r in results if isinstance(r, HTTPException)]
    accepted = [r for r in results if not isinstance(r, BaseException)]
    assert len(accepted) == 1
    assert [(e.status_code, e.detail) for e in refused] == [
        (BUSY, chat_service.TURN_IN_PROGRESS)
    ]
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]


async def test_a_claim_older_than_two_minutes_does_not_block(admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)
    await _age_claim(admin_engine, conv, 180)

    await _turn(user_a, conv)
    assert await _messages(admin_engine, conv) == [("user", PROMPT)] * 2


async def test_a_claim_younger_than_two_minutes_still_blocks(admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)
    await _age_claim(admin_engine, conv, 90)

    assert await _refused(user_a, conv) == BUSY


async def test_the_window_is_two_minutes():
    assert conversations_repo.TURN_WINDOW == timedelta(minutes=2)


async def test_a_lapsed_turn_ending_late_does_not_clear_the_newer_claim(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)
    await _age_claim(admin_engine, conv, 180)
    stale_claim = await _streaming_since(admin_engine, conv)

    _, newer_claim = await _turn(user_a, conv)
    await _reply(user_a, conv, stale_claim, _stream_of({"content": "late"}))

    assert await _streaming_since(admin_engine, conv) == newer_claim
    assert await _refused(user_a, conv) == BUSY


async def test_a_lapsed_turn_saving_late_does_not_clear_the_newer_claim(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)
    await _age_claim(admin_engine, conv, 180)
    stale_claim = await _streaming_since(admin_engine, conv)

    _, newer_claim = await _turn(user_a, conv)
    with _identity(user_a):
        await chat_service.persist_assistant_turn(
            conv, user_a.id, "late", claimed_at=stale_claim
        )
        await chat_service.release_claim(conv, stale_claim)

    assert await _streaming_since(admin_engine, conv) == newer_claim


async def test_two_conversations_of_one_user_can_each_have_a_reply_in_flight(
    admin_engine, user_a
):
    first = await make_conversation(admin_engine, user_a.id)
    second = await make_conversation(admin_engine, user_a.id)

    await _turn(user_a, first)
    await _turn(user_a, second)

    assert await _streaming_since(admin_engine, first) is not None
    assert await _streaming_since(admin_engine, second) is not None


async def test_a_new_conversation_is_created_already_claimed(admin_engine, user_a):
    conv, claimed_at = await _turn(user_a, None)

    assert claimed_at is not None
    assert await _refused(user_a, conv) == BUSY
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]


async def _set_updated_at(admin_engine, conv, value: datetime) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE conversations SET updated_at = :v WHERE id = :c"),
            {"c": conv, "v": value},
        )


async def _updated_at(admin_engine, conv):
    async with admin_engine.connect() as conn:
        return await conn.scalar(
            text("SELECT updated_at FROM conversations WHERE id = :c"), {"c": conv}
        )


async def test_claim_and_release_leave_updated_at_unchanged(admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    await _set_updated_at(admin_engine, conv, datetime(2020, 1, 1, tzinfo=UTC))
    known = await _updated_at(admin_engine, conv)

    with _identity(user_a):
        async with AsyncSessionLocal() as session, session.begin():
            claimed_at = await conversations_repo.claim_turn(session, user_a.id, conv)
    assert claimed_at is not None
    assert await _updated_at(admin_engine, conv) == known

    with _identity(user_a):
        async with AsyncSessionLocal() as session, session.begin():
            await conversations_repo.release_turn(session, conv, claimed_at)
    assert await _streaming_since(admin_engine, conv) is None
    assert await _updated_at(admin_engine, conv) == known


@pytest.fixture
def harness(monkeypatch):
    async def fake(messages, **kwargs):
        yield {"content": "ok"}

    monkeypatch.setattr(chat_router, "stream_completion_agentic", fake)


async def test_route_refuses_a_turn_while_a_claim_is_held_then_accepts_once_released(
    client, admin_engine, user_a, harness
):
    conv = await make_conversation(admin_engine, user_a.id)
    await _age_claim(admin_engine, conv, 0)
    body = {"prompt": PROMPT, "conversation_id": str(conv)}

    busy = await client.post("/api/chat", json=body, headers=bearer(user_a))
    assert busy.status_code == BUSY
    assert busy.json()["detail"] == chat_service.TURN_IN_PROGRESS
    assert await _messages(admin_engine, conv) == []

    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE conversations SET streaming_since = NULL WHERE id = :c"),
            {"c": conv},
        )
    ok = await client.post("/api/chat", json=body, headers=bearer(user_a))
    assert ok.status_code == 200
    assert await _streaming_since(admin_engine, conv) is None
