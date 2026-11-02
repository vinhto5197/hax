"""Stop: a running reply is cut short by its user. `Turn.stop()` (and
`turns.stop_turn(conversation_id)`, which finds the conversation's running
turn) saves what was written so far as the reply, through the normal save,
and frees the conversation; a stop before any text, or with only whitespace,
stores nothing and frees it. A shutdown drain still stores nothing.
`POST /api/conversations/{id}/stop` is 204 for the caller's own conversation,
running or not, and 404 for anyone else's.

Turns are started as the route starts them, with identity announced; seeds
and asserts go through admin_engine.
"""

import asyncio
import contextlib
import uuid

import pytest
from sqlalchemy import text

import apps.api.chat_service as chat_service
from apps.api import enqueue, turns
from packages.db.session import AsyncSessionLocal
from packages.db.user_context import current_user_id
from tests.api.conftest import bearer
from tests.api.factories import make_conversation

PROMPT = "what did I upload?"
# Bounds every wait on a turn: a hang fails the test instead of stalling it.
GUARD_SECONDS = 10
PART_1 = "Long reply, part 1. "
PART_2 = "Long reply, part 2. "
SOURCE = {
    "document_id": str(uuid.UUID(int=1)),
    "filename": "notes.txt",
    "chunk_idx": 0,
    "excerpt": "the excerpt",
    "distance": 0.1,
}


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


def _start(user, conv, claimed_at, stream_fn):
    """Start the reply's turn as `user`, as the route does."""
    with _identity(user):
        return turns.start_turn(stream_fn, [], conv, user.id, claimed_at)


def _stream(*events, until: asyncio.Event | None = None, then=(), calls=None):
    """A scripted model: `events`, then (once `until` is set) `then`."""

    async def stream_fn(messages, **kwargs):
        if calls is not None:
            calls.append(messages)
        for e in events:
            yield e
        if until is not None:
            await until.wait()
        for e in then:
            yield e

    return stream_fn


async def _read(listener, n: int) -> list:
    """The next `n` items of a listener, bounded."""
    async with asyncio.timeout(GUARD_SECONDS):
        return [await anext(listener) for _ in range(n)]


async def _rest(listener) -> list:
    """Every remaining item of a listener, to its end, bounded."""
    async with asyncio.timeout(GUARD_SECONDS):
        return [item async for item in listener]


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


async def _last_sources(admin_engine, conv):
    async with admin_engine.connect() as conn:
        return await conn.scalar(
            text(
                "SELECT sources FROM messages WHERE conversation_id = :c"
                " ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"c": conv},
        )


async def _active_queries(admin_engine, marker: str) -> int:
    async with admin_engine.connect() as conn:
        return await conn.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE state = 'active' AND query LIKE :m"
                " AND pid <> pg_backend_pid()"
            ),
            {"m": f"%{marker}%"},
        )


async def _until(predicate, seconds: float = 3.0) -> bool:
    """Polls an async predicate until it holds or `seconds` pass."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while loop.time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.05)
    return await predicate()


# --- Turn.stop / stop_turn --------------------------------------------------


async def test_a_stop_saves_the_partial_reply_ends_with_done_and_releases_the_claim(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a,
        conv,
        claimed_at,
        _stream(
            {"sources": [SOURCE]},
            {"content": PART_1},
            {"content": PART_2},
            until=asyncio.Event(),
            then=({"content": "never written"},),
        ),
    )
    listener = turn.listen()
    await _read(listener, 3)

    turns.stop_turn(conv)

    assert await _rest(listener) == ["done"]
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", PART_1 + PART_2),
    ]
    assert await _last_sources(admin_engine, conv) == [SOURCE]
    assert await _streaming_since(admin_engine, conv) is None


async def test_turn_stop_on_the_handle_saves_the_partial_like_stop_turn(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a, conv, claimed_at, _stream({"content": PART_1}, until=asyncio.Event())
    )
    listener = turn.listen()
    await _read(listener, 1)

    turn.stop()

    assert await _rest(listener) == ["done"]
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", PART_1),
    ]
    assert await _streaming_since(admin_engine, conv) is None


async def test_the_conversation_takes_a_new_turn_at_once_after_a_stop(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a, conv, claimed_at, _stream({"content": PART_1}, until=asyncio.Event())
    )
    listener = turn.listen()
    await _read(listener, 1)
    turns.stop_turn(conv)
    await _rest(listener)

    _, next_claim = await _turn(user_a, conv)

    assert next_claim is not None


async def test_a_stop_during_a_search_documents_call_cancels_its_query_releases_the_session_and_stores_the_text_so_far(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    marker = f"stop-test-{conv}"

    async def stream_fn(messages, **kwargs):
        yield {"content": "Let me look. "}
        yield {"status": "Searching documents…"}
        # A stand-in for search_documents: a slow query on the tool's session.
        async with AsyncSessionLocal() as session:
            await session.execute(text(f"SELECT pg_sleep(5) /* {marker} */"))
        yield {"content": "never written"}

    turn = _start(user_a, conv, claimed_at, stream_fn)
    listener = turn.listen()
    await _read(listener, 2)
    assert await _until(lambda: _active_queries_positive(admin_engine, marker))

    loop = asyncio.get_running_loop()
    started = loop.time()
    turns.stop_turn(conv)
    rest = await _rest(listener)
    elapsed = loop.time() - started

    assert rest == ["done"]
    assert elapsed < 3, "the stop waited for the tool's query instead of cancelling"
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "Let me look. "),
    ]
    assert await _streaming_since(admin_engine, conv) is None
    assert await _until(lambda: _no_active_queries(admin_engine, marker)), (
        "the tool's query was still running after the stop"
    )


async def _active_queries_positive(admin_engine, marker: str) -> bool:
    return await _active_queries(admin_engine, marker) > 0


async def _no_active_queries(admin_engine, marker: str) -> bool:
    return await _active_queries(admin_engine, marker) == 0


async def test_a_stop_with_only_whitespace_written_stores_nothing_ends_with_failed_and_releases(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a,
        conv,
        claimed_at,
        _stream({"content": "  \n"}, {"content": " \t "}, until=asyncio.Event()),
    )
    listener = turn.listen()
    await _read(listener, 2)

    turns.stop_turn(conv)

    assert await _rest(listener) == ["failed"]
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]
    assert await _streaming_since(admin_engine, conv) is None


async def test_a_stop_before_any_text_stores_nothing_ends_with_failed_and_releases(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a,
        conv,
        claimed_at,
        _stream({"status": "Searching documents…"}, until=asyncio.Event()),
    )
    listener = turn.listen()
    await _read(listener, 1)

    turns.stop_turn(conv)

    assert await _rest(listener) == ["failed"]
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]
    assert await _streaming_since(admin_engine, conv) is None


async def test_a_stop_that_arrives_before_the_turn_starts_streaming_stores_nothing_never_calls_the_model_and_releases(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    calls: list = []
    turn = _start(user_a, conv, claimed_at, _stream({"content": PART_1}, calls=calls))

    turn.stop()

    assert await _rest(turn.listen()) == ["failed"]
    assert calls == []
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]
    assert await _streaming_since(admin_engine, conv) is None


async def test_a_stop_after_the_model_stream_finished_stores_the_whole_reply(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a,
        conv,
        claimed_at,
        _stream({"content": PART_1}, {"content": PART_2}),
    )
    listener = turn.listen()
    await _read(listener, 2)

    turn.stop()

    assert await _rest(listener) == ["done"]
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", PART_1 + PART_2),
    ]
    assert await _streaming_since(admin_engine, conv) is None


async def test_a_stop_after_the_turn_ended_changes_nothing(admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(user_a, conv, claimed_at, _stream({"content": PART_1}))
    assert await _rest(turn.listen()) == [{"content": PART_1}, "done"]

    turn.stop()
    turns.stop_turn(conv)
    await asyncio.sleep(0)

    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", PART_1),
    ]


async def test_stop_turn_for_a_conversation_with_no_running_turn_does_nothing(
    admin_engine, user_a
):
    turns.stop_turn(uuid.uuid4())
    conv = await make_conversation(admin_engine, user_a.id)
    turns.stop_turn(conv)

    assert await _messages(admin_engine, conv) == []


async def test_stop_turn_stops_only_its_own_conversations_turn(admin_engine, user_a):
    stopped = await make_conversation(admin_engine, user_a.id)
    running = await make_conversation(admin_engine, user_a.id)
    _, stopped_claim = await _turn(user_a, stopped)
    _, running_claim = await _turn(user_a, running)
    go_on = asyncio.Event()
    stopped_turn = _start(
        user_a,
        stopped,
        stopped_claim,
        _stream({"content": PART_1}, until=asyncio.Event()),
    )
    running_turn = _start(
        user_a,
        running,
        running_claim,
        _stream({"content": PART_1}, until=go_on, then=({"content": PART_2},)),
    )
    stopped_listener = stopped_turn.listen()
    running_listener = running_turn.listen()
    await _read(stopped_listener, 1)
    await _read(running_listener, 1)

    turns.stop_turn(stopped)
    assert await _rest(stopped_listener) == ["done"]
    go_on.set()

    assert await _rest(running_listener) == [{"content": PART_2}, "done"]
    assert await _messages(admin_engine, running) == [
        ("user", PROMPT),
        ("assistant", PART_1 + PART_2),
    ]


async def test_a_second_turns_registry_entry_survives_the_first_turns_end_so_stop_still_reaches_it(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, first_claim = await _turn(user_a, conv)
    first_go_on = asyncio.Event()
    first = _start(
        user_a,
        conv,
        first_claim,
        _stream({"content": "first. "}, until=first_go_on),
    )
    first_listener = first.listen()
    await _read(first_listener, 1)
    # The first turn's claim lapses, so a second turn claims the same
    # conversation in the same process while the first still runs.
    await _age_claim(admin_engine, conv, 600)
    _, second_claim = await _turn(user_a, conv)
    second = _start(
        user_a,
        conv,
        second_claim,
        _stream({"content": "second. "}, until=asyncio.Event()),
    )
    second_listener = second.listen()
    await _read(second_listener, 1)

    first_go_on.set()
    await _rest(first_listener)
    turns.stop_turn(conv)

    assert await _rest(second_listener) == ["done"]
    assert (await _messages(admin_engine, conv))[-1] == ("assistant", "second. ")
    assert await _streaming_since(admin_engine, conv) is None


async def test_a_shutdown_drain_still_stores_nothing_of_a_partial_reply_and_releases(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a, conv, claimed_at, _stream({"content": PART_1}, until=asyncio.Event())
    )
    listener = turn.listen()
    await _read(listener, 1)

    await turns.drain_turns(0)

    assert await _rest(listener) == ["failed"]
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]
    assert await _streaming_since(admin_engine, conv) is None


def _stream_stopped_as_cancelled(turn_box: list):
    """A model that writes PART_1 and waits; when its consumption is
    cancelled from outside, the user's Stop lands in that same moment, so the
    turn sees a stop and an outer cancel at once."""

    async def stream_fn(messages, **kwargs):
        yield {"content": PART_1}
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            turn_box[0].stop()
            raise

    return stream_fn


async def test_a_drain_that_lands_with_a_stop_wins_and_stores_nothing(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    box: list = []
    turn = _start(user_a, conv, claimed_at, _stream_stopped_as_cancelled(box))
    box.append(turn)
    listener = turn.listen()
    await _read(listener, 1)

    await turns.drain_turns(0)

    assert turn._stopped
    assert await _rest(listener) == ["failed"]
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]
    assert await _streaming_since(admin_engine, conv) is None


async def test_a_deadline_that_lands_with_a_stop_stores_nothing(
    admin_engine, user_a, monkeypatch
):
    monkeypatch.setattr(turns, "TURN_DEADLINE_SECONDS", 0.5)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    box: list = []
    turn = _start(user_a, conv, claimed_at, _stream_stopped_as_cancelled(box))
    box.append(turn)
    listener = turn.listen()

    assert await _rest(listener) == [{"content": PART_1}, "failed"]
    assert turn._stopped
    assert await _messages(admin_engine, conv) == [("user", PROMPT)]
    assert await _streaming_since(admin_engine, conv) is None


# --- POST /api/conversations/{id}/stop ---------------------------------------


async def test_the_stop_route_stops_the_owners_running_turn_with_204_and_the_partial_is_saved(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a, conv, claimed_at, _stream({"content": PART_1}, until=asyncio.Event())
    )
    listener = turn.listen()
    await _read(listener, 1)

    r = await client.post(f"/api/conversations/{conv}/stop", headers=bearer(user_a))

    assert r.status_code == 204
    assert r.content == b""
    assert await _rest(listener) == ["done"]
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", PART_1),
    ]
    assert await _streaming_since(admin_engine, conv) is None


async def test_stopping_another_users_conversation_is_404_and_the_owners_turn_runs_on(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, user_b
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    go_on = asyncio.Event()
    turn = _start(
        user_a,
        conv,
        claimed_at,
        _stream({"content": PART_1}, until=go_on, then=({"content": PART_2},)),
    )
    listener = turn.listen()
    await _read(listener, 1)

    r = await client.post(f"/api/conversations/{conv}/stop", headers=bearer(user_b))
    await asyncio.sleep(0.1)
    go_on.set()

    assert r.status_code == 404
    assert r.json() == {"detail": "conversation not found"}
    assert await _rest(listener) == [{"content": PART_2}, "done"]
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", PART_1 + PART_2),
    ]


async def test_stopping_an_unknown_conversation_is_404(client, user_a):
    r = await client.post(
        f"/api/conversations/{uuid.uuid4()}/stop", headers=bearer(user_a)
    )

    assert r.status_code == 404
    assert r.json() == {"detail": "conversation not found"}


async def test_stopping_an_own_conversation_with_no_running_turn_is_204(
    client, admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)

    r = await client.post(f"/api/conversations/{conv}/stop", headers=bearer(user_a))

    assert r.status_code == 204
    assert r.content == b""


async def test_stopping_twice_is_204_both_times(client, admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await _turn(user_a, conv)
    turn = _start(
        user_a, conv, claimed_at, _stream({"content": PART_1}, until=asyncio.Event())
    )
    listener = turn.listen()
    await _read(listener, 1)

    first = await client.post(f"/api/conversations/{conv}/stop", headers=bearer(user_a))
    await _rest(listener)
    second = await client.post(
        f"/api/conversations/{conv}/stop", headers=bearer(user_a)
    )

    assert (first.status_code, second.status_code) == (204, 204)
    assert await _messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", PART_1),
    ]


async def test_stopping_without_a_session_is_401(client, admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)

    r = await client.post(f"/api/conversations/{conv}/stop")

    assert r.status_code == 401
