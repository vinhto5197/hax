"""A reply whose turn claim was taken over before its save is not a saved
reply: the save stores nothing (the release is conditional on the turn's own
claim), so the stream ends the way a failed reply ends — a `reply_failed`
frame and no `[DONE]` — and a WARNING is logged without any message content.
A reply whose claim is still held is stored and ends with `[DONE]`.

The takeover is staged for real, not by mocking the release: while the model
is mid-reply, the claim is aged past the window (admin_engine) and a second
user turn re-claims the conversation. The turn's save then finds a claim
that is no longer its own and releases nothing.
"""

import logging

import pytest

import apps.api.chat_service as chat_service
import apps.api.routers.chat as chat_router
from tests.api.conftest import as_user, bearer, wait_for_turns
from tests.api.factories import make_conversation
from tests.api.helpers import (
    DONE,
    FAILED_FRAME,
    PROMPT,
    age_claim,
    sse_events,
    start_turn_as,
    stored_messages,
    streaming_since,
    user_turn,
)

pytestmark = pytest.mark.usefixtures("no_background_outlives_its_test")

DONE_FRAME = "data: [DONE]\n\n"
REPLY_FAILED = 'data: {"error": "reply_failed"}\n\n'
SECOND = "a second question from another tab"
FIRST_PIECE = "zebra-quartz "
SECOND_PIECE = "reply-that-lost-its-claim"
# Past the two-minute window, so the second user turn may take the claim.
STALE_SECONDS = 180


def _taken_over_mid_reply(admin_engine, user, conv, newer: list):
    """A scripted model that, between its two pieces, lets a second request
    take the conversation's claim; the newer claim lands in `newer`."""

    async def stream_fn(messages, **kwargs):
        yield {"content": FIRST_PIECE}
        await age_claim(admin_engine, conv, STALE_SECONDS)
        _, claimed = await user_turn(user, conv, SECOND)
        newer.append(claimed)
        yield {"content": SECOND_PIECE}

    return stream_fn


def _plain(*events):
    async def stream_fn(messages, **kwargs):
        for event in events:
            yield event

    return stream_fn


async def _listen(user, turn, conv) -> list[str]:
    with as_user(user):
        return [frame async for frame in chat_service.event_stream(turn, conv)]


async def test_a_reply_whose_claim_was_taken_over_ends_with_reply_failed_and_no_done(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await user_turn(user_a, conv)
    newer: list = []
    turn = start_turn_as(
        user_a,
        conv,
        claimed_at,
        _taken_over_mid_reply(admin_engine, user_a, conv, newer),
    )

    frames = await _listen(user_a, turn, conv)
    await wait_for_turns()

    assert newer, "the takeover never ran"
    assert DONE_FRAME not in frames
    assert frames[-1] == REPLY_FAILED
    assert frames.count(REPLY_FAILED) == 1


async def test_a_reply_whose_claim_was_taken_over_stores_nothing_and_leaves_the_newer_claim(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await user_turn(user_a, conv)
    newer: list = []
    turn = start_turn_as(
        user_a,
        conv,
        claimed_at,
        _taken_over_mid_reply(admin_engine, user_a, conv, newer),
    )

    await _listen(user_a, turn, conv)
    await wait_for_turns()

    assert await stored_messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("user", SECOND),
    ]
    assert await streaming_since(admin_engine, conv) == newer[0]


async def test_a_reply_whose_claim_was_taken_over_ends_the_chat_route_stream_with_reply_failed_and_no_done(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, monkeypatch
):
    conv = await make_conversation(admin_engine, user_a.id)
    newer: list = []
    # The route's model stream, patched where conftest's model_stream patches
    # it: that fixture scripts events only, and this stream must act mid-reply.
    monkeypatch.setattr(
        chat_router,
        "stream_completion_agentic",
        _taken_over_mid_reply(admin_engine, user_a, conv, newer),
    )

    r = await client.post(
        "/api/chat",
        json={"prompt": PROMPT, "conversation_id": str(conv)},
        headers=bearer(user_a),
    )
    await wait_for_turns()

    assert r.status_code == 200
    events = sse_events(r.text)
    assert newer, "the takeover never ran"
    assert DONE not in events
    assert events[-1] == FAILED_FRAME
    assert await stored_messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("user", SECOND),
    ]


async def test_a_reply_whose_claim_is_still_held_is_stored_and_ends_with_done(
    admin_engine, user_a
):
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await user_turn(user_a, conv)
    turn = start_turn_as(
        user_a,
        conv,
        claimed_at,
        _plain({"content": FIRST_PIECE}, {"content": SECOND_PIECE}),
    )

    frames = await _listen(user_a, turn, conv)
    await wait_for_turns()

    assert frames[-1] == DONE_FRAME
    assert REPLY_FAILED not in frames
    assert await stored_messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", FIRST_PIECE + SECOND_PIECE),
    ]
    assert await streaming_since(admin_engine, conv) is None


async def test_a_reply_whose_claim_was_taken_over_logs_a_warning_without_message_content(  # noqa: E501 — the name is the behaviour line
    admin_engine, user_a, caplog
):
    caplog.set_level(logging.DEBUG)
    conv = await make_conversation(admin_engine, user_a.id)
    _, claimed_at = await user_turn(user_a, conv)
    newer: list = []
    turn = start_turn_as(
        user_a,
        conv,
        claimed_at,
        _taken_over_mid_reply(admin_engine, user_a, conv, newer),
    )

    await _listen(user_a, turn, conv)
    await wait_for_turns()

    assert newer, "the takeover never ran"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, caplog.text
    for secret in (PROMPT, SECOND, FIRST_PIECE.strip(), SECOND_PIECE):
        assert secret not in caplog.text
