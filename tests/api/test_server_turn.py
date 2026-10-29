"""The server owns the turn: a reply runs as a task (apps/api/turns.py) that
outlives the request which started it. The task saves the whole reply and
releases the claim, or stores nothing and releases on a failure, its deadline
or a shutdown drain; the request only listens, with a keepalive comment while
nothing arrives. While the task runs, a heartbeat refreshes the claim, so a
reply longer than the window still reads as in progress. `replying` on the
conversation detail is that live claim, read with the conversation.

Turns are started as the route starts them, with identity announced; seeds,
clock moves and asserts go through admin_engine. Intervals and windows are
shortened through their module constants, never slept out.
"""

import asyncio
import contextlib
import json
import re
import uuid
from datetime import timedelta

import asyncpg
import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.util import await_only

import apps.api.chat_service as chat_service
from apps.api import enqueue, turns
from packages.db import engine
from packages.db.repos import conversations as conversations_repo
from packages.db.session import AsyncSessionLocal
from packages.db.user_context import current_user_id
from tests.api.conftest import ADMIN_URL, bearer, wait_for_turns
from tests.api.factories import make_conversation

PROMPT = "what did I upload?"
BUSY = 409
DONE_FRAME = "data: [DONE]\n\n"
REPLY_FAILED = 'data: {"error": "reply_failed"}\n\n'
# Bounds every wait on a turn: a hang fails the test instead of stalling it.
GUARD_SECONDS = 10


class DatabaseDown(Exception):
    pass


class ModelDown(Exception):
    pass


@pytest.fixture(autouse=True)
async def no_turn_outlives_its_test():
    yield
    await turns.drain_turns(5)
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
    return excinfo.value.status_code


def _start(user, conv, claimed_at, stream_fn):
    """Start the reply's turn as `user`, as the route does."""
    with _identity(user):
        return turns.start_turn(stream_fn, [], conv, user.id, claimed_at)


async def _listen(user, turn, conv) -> list[str]:
    """Every frame the request would send, to the end."""
    async with asyncio.timeout(GUARD_SECONDS):
        with _identity(user):
            return [frame async for frame in chat_service.event_stream(turn, conv)]


def _stream(*events, until: asyncio.Event | None = None, then=(), error=None):
    """A scripted model: `events`, then (once `until` is set) `then`, then
    `error` raised, if given."""

    async def stream_fn(messages, **kwargs):
        for e in events:
            yield e
        if until is not None:
            await until.wait()
        for e in then:
            yield e
        if error is not None:
            raise error

    return stream_fn


def _replace(monkeypatch, home, name, replacement) -> None:
    """Swap `name` on its home module and on every module of the turn path
    that holds its own reference to it."""
    monkeypatch.setattr(home, name, replacement)
    for module in (turns, chat_service):
        if module is not home and hasattr(module, name):
            monkeypatch.setattr(module, name, replacement)


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


async def _detail(client, user, conv) -> dict:
    r = await client.get(f"/api/conversations/{conv}", headers=bearer(user))
    assert r.status_code == 200
    return r.json()


# --- the turn's listener contract -------------------------------------------


async def test_listen_yields_each_event_in_order_then_done(admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    events = [
        {"status": "Searching your documents"},
        {"content": "a"},
        {"content": "b"},
    ]
    turn = _start(user_a, conv, claimed_at, _stream(*events))

    async with asyncio.timeout(GUARD_SECONDS):
        got = [item async for item in turn.listen()]

    assert got == [*events, "done"]


async def test_listen_ends_with_failed_after_a_model_error(admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a, conv, claimed_at, _stream({"content": "a"}, error=ModelDown())
    )

    async with asyncio.timeout(GUARD_SECONDS):
        got = [item async for item in turn.listen()]

    assert got == [{"content": "a"}, "failed"]


# --- the reply outlives its listener ----------------------------------------


async def test_a_client_that_disconnects_before_reading_anything_still_gets_its_reply_stored_and_the_conversation_freed(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    go = asyncio.Event()
    turn = _start(
        user_a,
        conv,
        claimed_at,
        _stream({"content": "Hello "}, until=go, then=[{"content": "world."}]),
    )
    with _identity(user_a):
        gen = chat_service.event_stream(turn, conv)
        await gen.aclose()

    go.set()
    await wait_for_turns()

    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "Hello world."),
    ]
    assert await _streaming_since(admin_engine, conv) is None
    await _turn(user_a, conv)


async def test_a_chat_request_whose_client_is_gone_before_the_first_byte_still_gets_its_reply_stored(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a, model_stream
):
    from apps.api.main import app

    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Hello "}, {"content": "world."})
    body = json.dumps({"prompt": PROMPT, "conversation_id": str(conv)}).encode()
    headers = [
        (b"host", b"test"),
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        *((k.lower().encode(), v.encode()) for k, v in bearer(user_a).items()),
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/chat",
        "raw_path": b"/api/chat",
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        pass

    async with asyncio.timeout(GUARD_SECONDS):
        await app(scope, receive, send)
    await wait_for_turns()

    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "Hello world."),
    ]
    assert await _streaming_since(admin_engine, conv) is None


async def test_the_chat_route_streams_the_reply_and_the_turn_stores_it_whole(
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Hello "}, {"content": "world."})

    r = await client.post(
        "/api/chat",
        json={"prompt": PROMPT, "conversation_id": str(conv)},
        headers=bearer(user_a),
    )
    await wait_for_turns()

    assert r.status_code == 200
    assert r.text.endswith(DONE_FRAME)
    assert '"Hello "' in r.text and '"world."' in r.text
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "Hello world."),
    ]
    assert await _streaming_since(admin_engine, conv) is None


async def test_a_database_error_while_saving_ends_the_listener_with_reply_failed_and_no_done(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a, monkeypatch
):
    async def save(*args, **kwargs):
        raise DatabaseDown()

    _replace(monkeypatch, chat_service, "persist_assistant_turn", save)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(user_a, conv, claimed_at, _stream({"content": "Hello"}))

    frames = await _listen(user_a, turn, conv)

    assert frames[-1] == REPLY_FAILED
    assert DONE_FRAME not in frames
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]


async def test_a_save_that_raises_leaves_the_conversation_claimable_at_once(
    admin_engine, user_a, monkeypatch
):
    async def save(*args, **kwargs):
        raise DatabaseDown()

    _replace(monkeypatch, chat_service, "persist_assistant_turn", save)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(user_a, conv, claimed_at, _stream({"content": "Hello"}))

    frames = await _listen(user_a, turn, conv)

    assert frames[-1] == REPLY_FAILED
    assert await _streaming_since(admin_engine, conv) is None
    assert (await _turn(user_a, conv))[0] == conv


# --- the heartbeat ----------------------------------------------------------


def _slow_refresh(monkeypatch, *, in_flight: asyncio.Event, hold: float) -> list:
    """The first heartbeat refresh commits for real, then holds its answer for
    `hold` seconds with `in_flight` set: a refresh still running when the
    turn ends. Returns every refresh's result."""
    real = conversations_repo.refresh_turn
    results: list = []

    async def refresh(*args, **kwargs):
        new = await real(*args, **kwargs)
        results.append(new)
        if len(results) == 1:
            in_flight.set()
            await asyncio.sleep(hold)
        return new

    _replace(monkeypatch, conversations_repo, "refresh_turn", refresh)
    return results


async def test_a_heartbeat_refresh_in_flight_when_the_reply_finishes_does_not_leave_the_claim_held(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a, monkeypatch
):
    monkeypatch.setattr(turns, "HEARTBEAT_SECONDS", 0.05)
    in_flight = asyncio.Event()
    results = _slow_refresh(monkeypatch, in_flight=in_flight, hold=0.3)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a, conv, claimed_at, _stream({"content": "Hello"}, until=in_flight)
    )

    frames = await _listen(user_a, turn, conv)
    await wait_for_turns()

    assert results and results[0] is not None
    assert frames[-1] == DONE_FRAME
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "Hello"),
    ]
    assert await _streaming_since(admin_engine, conv) is None


async def test_stopping_the_heartbeat_while_a_refresh_is_in_flight_still_releases_the_claim(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a, monkeypatch
):
    monkeypatch.setattr(turns, "HEARTBEAT_SECONDS", 0.05)
    in_flight = asyncio.Event()
    results = _slow_refresh(monkeypatch, in_flight=in_flight, hold=0.3)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a,
        conv,
        claimed_at,
        _stream({"content": "partial"}, until=in_flight, error=ModelDown()),
    )

    frames = await _listen(user_a, turn, conv)
    await wait_for_turns()

    assert results and results[0] is not None
    assert frames[-1] == REPLY_FAILED
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]
    assert await _streaming_since(admin_engine, conv) is None
    await _turn(user_a, conv)


async def test_a_heartbeat_refresh_that_raises_is_retried_and_the_reply_still_completes(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a, monkeypatch
):
    monkeypatch.setattr(turns, "HEARTBEAT_SECONDS", 0.05)
    real = conversations_repo.refresh_turn
    calls: list[str] = []
    retried = asyncio.Event()

    async def refresh(*args, **kwargs):
        calls.append("call")
        if len(calls) == 1:
            raise DatabaseDown()
        new = await real(*args, **kwargs)
        retried.set()
        return new

    _replace(monkeypatch, conversations_repo, "refresh_turn", refresh)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a,
        conv,
        claimed_at,
        _stream({"content": "Hello "}, until=retried, then=[{"content": "world."}]),
    )

    frames = await _listen(user_a, turn, conv)
    await wait_for_turns()

    assert len(calls) >= 2
    assert frames[-1] == DONE_FRAME
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "Hello world."),
    ]
    assert await _streaming_since(admin_engine, conv) is None


async def test_stopping_the_heartbeat_mid_interval_ends_the_turn_promptly_not_after_the_interval(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a, monkeypatch
):
    monkeypatch.setattr(turns, "HEARTBEAT_SECONDS", 30)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)

    async def stream_fn(messages, **kwargs):
        yield {"content": "Hello"}
        await asyncio.sleep(0.2)

    loop = asyncio.get_running_loop()
    started = loop.time()
    turn = _start(user_a, conv, claimed_at, stream_fn)
    frames = await _listen(user_a, turn, conv)
    elapsed = loop.time() - started

    assert frames[-1] == DONE_FRAME
    assert elapsed < 5
    assert await _streaming_since(admin_engine, conv) is None


async def test_a_running_turns_claim_is_refreshed_past_the_window(
    client, admin_engine, user_a, monkeypatch
):
    monkeypatch.setattr(conversations_repo, "TURN_WINDOW", timedelta(seconds=1.5))
    monkeypatch.setattr(turns, "HEARTBEAT_SECONDS", 0.25)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    go = asyncio.Event()
    turn = _start(
        user_a,
        conv,
        claimed_at,
        _stream({"content": "Hello "}, until=go, then=[{"content": "world."}]),
    )
    listener = asyncio.create_task(_listen(user_a, turn, conv))

    await asyncio.sleep(2.5)
    assert await _refused(user_a, conv) == BUSY
    assert (await _detail(client, user_a, conv))["replying"] is True
    assert await _streaming_since(admin_engine, conv) > claimed_at

    go.set()
    frames = await listener
    await wait_for_turns()

    assert frames[-1] == DONE_FRAME
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "Hello world."),
    ]
    assert await _streaming_since(admin_engine, conv) is None


async def test_the_heartbeat_interval_is_thirty_seconds():
    assert turns.HEARTBEAT_SECONDS == 30


# --- refresh_turn -----------------------------------------------------------


async def _refresh(user, conv, claimed_at):
    with _identity(user):
        async with AsyncSessionLocal() as session, session.begin():
            return await conversations_repo.refresh_turn(session, conv, claimed_at)


async def test_a_refresh_moves_the_claim_to_now_and_returns_the_new_value(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)
    await _age_claim(admin_engine, conv, 90)
    aged = await _streaming_since(admin_engine, conv)

    refreshed = await _refresh(user_a, conv, aged)

    assert refreshed is not None
    assert refreshed - aged >= timedelta(seconds=89)
    assert await _streaming_since(admin_engine, conv) == refreshed


async def test_a_lapsed_turns_refresh_returns_none_and_leaves_the_newer_claim(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)
    await _age_claim(admin_engine, conv, 180)
    stale_claim = await _streaming_since(admin_engine, conv)
    _, newer_claim = await _turn(user_a, conv)

    assert await _refresh(user_a, conv, stale_claim) is None
    assert await _streaming_since(admin_engine, conv) == newer_claim


async def test_a_refresh_after_the_release_returns_none_and_does_not_reclaim_the_conversation(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    with _identity(user_a):
        await chat_service.release_claim(conv, claimed_at)

    assert await _refresh(user_a, conv, claimed_at) is None
    assert await _streaming_since(admin_engine, conv) is None


async def test_a_refresh_leaves_updated_at_unchanged(admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    async with admin_engine.connect() as conn:
        before = await conn.scalar(
            text("SELECT updated_at FROM conversations WHERE id = :c"), {"c": conv}
        )

    assert await _refresh(user_a, conv, claimed_at) is not None
    async with admin_engine.connect() as conn:
        after = await conn.scalar(
            text("SELECT updated_at FROM conversations WHERE id = :c"), {"c": conv}
        )
    assert after == before


# --- the deadline -----------------------------------------------------------


async def test_a_turn_past_its_deadline_ends_as_reply_failed_and_frees_the_conversation(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a, monkeypatch
):
    monkeypatch.setattr(turns, "TURN_DEADLINE_SECONDS", 0.3)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    never = asyncio.Event()
    turn = _start(
        user_a, conv, claimed_at, _stream({"content": "partial"}, until=never)
    )

    frames = await _listen(user_a, turn, conv)
    await wait_for_turns()

    assert frames[-1] == REPLY_FAILED
    assert DONE_FRAME not in frames
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]
    assert await _streaming_since(admin_engine, conv) is None
    await _turn(user_a, conv)


async def test_the_turn_deadline_is_ten_minutes():
    assert turns.TURN_DEADLINE_SECONDS == 600


# --- the keepalive ----------------------------------------------------------


async def test_the_listener_sends_a_keepalive_comment_while_no_event_arrives(
    admin_engine, user_a, monkeypatch
):
    monkeypatch.setattr(chat_service, "KEEPALIVE_SECONDS", 0.1)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    go = asyncio.Event()
    turn = _start(
        user_a,
        conv,
        claimed_at,
        _stream({"content": "Hello "}, until=go, then=[{"content": "world."}]),
    )

    frames: list[str] = []
    async with asyncio.timeout(GUARD_SECONDS):
        with _identity(user_a):
            async for frame in chat_service.event_stream(turn, conv):
                frames.append(frame)
                if frame.startswith(":"):
                    go.set()

    keepalives = [i for i, f in enumerate(frames) if f.startswith(":")]
    assert keepalives, frames
    assert all(frames[i] == ": keepalive\n\n" for i in keepalives)
    hello = next(i for i, f in enumerate(frames) if '"Hello "' in f)
    world = next(i for i, f in enumerate(frames) if '"world."' in f)
    assert hello < keepalives[0] < world
    assert frames[-1] == DONE_FRAME


async def test_the_keepalive_interval_is_fifteen_seconds():
    assert chat_service.KEEPALIVE_SECONDS == 15


# --- drain_turns ------------------------------------------------------------


async def test_drain_turns_lets_a_finishing_turn_save_and_cancels_one_past_the_timeout_which_stores_nothing_and_releases(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a
):
    finishing = await make_conversation(admin_engine, user_a.id)
    stuck = await make_conversation(admin_engine, user_a.id)
    _, finishing_claim = await _turn(user_a, finishing)
    _, stuck_claim = await _turn(user_a, stuck)

    async def soon(messages, **kwargs):
        await asyncio.sleep(0.2)
        yield {"content": "made it"}

    _start(user_a, finishing, finishing_claim, soon)
    _start(
        user_a,
        stuck,
        stuck_claim,
        _stream({"content": "partial"}, until=asyncio.Event()),
    )

    loop = asyncio.get_running_loop()
    started = loop.time()
    await turns.drain_turns(1.0)
    elapsed = loop.time() - started

    assert elapsed < 1.0 + 3
    assert await _messages(admin_engine, finishing) == [
        ("user", PROMPT),
        ("assistant", "made it"),
    ]
    assert await _streaming_since(admin_engine, finishing) is None
    assert await _messages(admin_engine, stuck) == [("user", PROMPT)]
    assert await _streaming_since(admin_engine, stuck) is None


async def test_a_turn_cancelled_by_drain_turns_ends_its_listener_with_failed(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a, conv, claimed_at, _stream({"content": "partial"}, until=asyncio.Event())
    )

    await turns.drain_turns(0.2)
    async with asyncio.timeout(GUARD_SECONDS):
        got = [item async for item in turn.listen()]

    assert got[-1] == "failed"
    assert "done" not in got


async def test_a_drain_cancel_that_lands_during_a_save_that_commits_ends_the_listener_with_done(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a, monkeypatch
):
    real_save = chat_service.persist_assistant_turn
    saving = asyncio.Event()

    async def slow_save(*args, **kwargs):
        saving.set()
        await asyncio.sleep(0.5)
        return await real_save(*args, **kwargs)

    _replace(monkeypatch, chat_service, "persist_assistant_turn", slow_save)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(user_a, conv, claimed_at, _stream({"content": "Hello"}))

    async with asyncio.timeout(GUARD_SECONDS):
        await saving.wait()
        await turns.drain_turns(0.05)
        got = [item async for item in turn.listen()]

    assert got[-1] == "done"
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "Hello"),
    ]
    assert await _streaming_since(admin_engine, conv) is None


# --- the client-chosen message id -------------------------------------------


async def _message_ids(admin_engine, conv) -> list[tuple[str, uuid.UUID]]:
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT role, id FROM messages WHERE conversation_id = :c"
                " ORDER BY created_at, id"
            ),
            {"c": conv},
        )
        return [(role, id_) for role, id_ in rows]


async def test_a_send_with_a_message_id_stores_the_user_message_under_that_id(
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    message_id = uuid.uuid4()
    model_stream({"content": "Hello."})

    r = await client.post(
        "/api/chat",
        json={
            "prompt": PROMPT,
            "conversation_id": str(conv),
            "message_id": str(message_id),
        },
        headers=bearer(user_a),
    )
    await wait_for_turns()

    assert r.status_code == 200
    stored = await _message_ids(admin_engine, conv)
    assert [role for role, _ in stored] == ["user", "assistant"]
    assert stored[0][1] == message_id


@pytest.mark.parametrize("new_chat", [False, True], ids=["existing", "new chat"])
async def test_a_second_send_with_the_same_message_id_gets_409_and_stores_nothing(
    client, admin_engine, user_a, model_stream, new_chat
):
    conv = await make_conversation(admin_engine, user_a.id)
    message_id = str(uuid.uuid4())
    model_stream({"content": "Hello."})
    first = await client.post(
        "/api/chat",
        json={"prompt": PROMPT, "conversation_id": str(conv), "message_id": message_id},
        headers=bearer(user_a),
    )
    await wait_for_turns()
    assert first.status_code == 200

    again = await client.post(
        "/api/chat",
        json={
            "prompt": PROMPT,
            "conversation_id": None if new_chat else str(conv),
            "message_id": message_id,
        },
        headers=bearer(user_a),
    )

    assert again.status_code == 409
    assert again.json()["detail"] == "This message was already sent."
    assert [role for role, _ in await _message_ids(admin_engine, conv)] == [
        "user",
        "assistant",
    ]
    assert await _streaming_since(admin_engine, conv) is None
    async with admin_engine.connect() as conn:
        assert (
            await conn.scalar(
                text("SELECT count(*) FROM conversations WHERE user_id = :u"),
                {"u": user_a.id},
            )
            == 1
        )


# --- replying on the conversation detail ------------------------------------


async def test_a_conversation_that_never_had_a_turn_is_not_replying(
    client, admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)

    assert (await _detail(client, user_a, conv))["replying"] is False


async def test_replying_is_true_while_the_claim_is_held(client, admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)

    detail = await _detail(client, user_a, conv)

    assert detail["replying"] is True
    assert [m["role"] for m in detail["messages"]] == ["user"]


async def test_replying_is_true_for_a_claim_still_inside_the_window(
    client, admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)
    await _age_claim(admin_engine, conv, 90)

    assert (await _detail(client, user_a, conv))["replying"] is True


async def test_replying_is_false_once_the_reply_is_saved_and_the_claim_released(
    client, admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(user_a, conv, claimed_at, _stream({"content": "done"}))
    await _listen(user_a, turn, conv)

    detail = await _detail(client, user_a, conv)

    assert detail["replying"] is False
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


async def test_replying_is_false_when_the_claim_is_stale(client, admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)
    await _age_claim(admin_engine, conv, 180)

    assert (await _detail(client, user_a, conv))["replying"] is False


async def test_replying_and_the_messages_come_from_one_consistent_read(
    client, admin_engine, user_a
):
    """The reply is saved (and the claim cleared) the moment the detail's
    first read of the conversation or its messages has run: the response may
    show the reply, or still be replying, but never free with no reply."""
    conv = await make_conversation(admin_engine, user_a.id)
    await _turn(user_a, conv)
    saver = await asyncpg.connect(dsn=ADMIN_URL)
    landed = False

    async def save_reply() -> None:
        async with saver.transaction():
            await saver.execute(
                "INSERT INTO messages (conversation_id, role, content)"
                " VALUES ($1, 'assistant', 'the reply')",
                conv,
            )
            await saver.execute(
                "UPDATE conversations SET streaming_since = NULL WHERE id = $1", conv
            )

    def land_the_reply(conn, cursor, statement, parameters, context, executemany):
        nonlocal landed
        if landed or not re.search(r"\bFROM (conversations|messages)\b", statement):
            return
        landed = True
        await_only(save_reply())

    event.listen(engine.sync_engine, "after_cursor_execute", land_the_reply)
    try:
        detail = await _detail(client, user_a, conv)
    finally:
        event.remove(engine.sync_engine, "after_cursor_execute", land_the_reply)
        await saver.close()

    assert landed
    roles = [m["role"] for m in detail["messages"]]
    assert not (detail["replying"] is False and roles[-1] == "user"), detail
