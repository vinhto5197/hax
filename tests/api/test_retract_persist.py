"""A {"retract": text} harness event withdraws narration: the route forwards
it to the browser as an SSE frame and stores the reply without that text. A
retract that does not match the end of what was streamed changes nothing
stored. Narration retracted with nothing after it stores what an empty reply
stores. Every test goes through POST /api/chat with the model scripted by
conftest's `model_stream`; asserts go through admin_engine."""

import pytest

from tests.api.conftest import bearer, wait_for_turns
from tests.api.factories import make_conversation
from tests.api.helpers import (
    PROMPT,
    sse_events,
    stored_messages,
    streaming_since,
)

pytestmark = pytest.mark.usefixtures("no_background_outlives_its_test")


async def _post(client, user, conv):
    return await client.post(
        "/api/chat",
        json={"prompt": PROMPT, "conversation_id": str(conv)},
        headers=bearer(user),
    )


async def test_retracted_narration_is_not_stored_and_its_retract_frame_reaches_the_browser(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream(
        {"content": "Let me look."},
        {"retract": "Let me look."},
        {"content": "The answer."},
    )

    r = await _post(client, user_a, conv)
    await wait_for_turns()

    assert r.status_code == 200
    events = sse_events(r.text)
    assert {"retract": "Let me look."} in events
    assert events.index({"content": "Let me look."}) < events.index(
        {"retract": "Let me look."}
    )
    assert events.index({"retract": "Let me look."}) < events.index(
        {"content": "The answer."}
    )
    assert await stored_messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "The answer."),
    ]


async def test_a_retract_that_is_not_the_end_of_the_streamed_text_leaves_the_stored_reply_unchanged(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream(
        {"content": "Let me look."},
        {"content": " The answer."},
        {"retract": "Let me look."},
    )

    r = await _post(client, user_a, conv)
    await wait_for_turns()

    assert r.status_code == 200
    assert await stored_messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "Let me look. The answer."),
    ]


async def test_narration_retracted_with_nothing_after_it_is_treated_like_an_empty_reply(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream
):
    # The baseline: what the route does today for a model that streams nothing.
    empty_conv = await make_conversation(admin_engine, user_a.id)
    model_stream()
    empty = await _post(client, user_a, empty_conv)
    await wait_for_turns()
    empty_stored = await stored_messages(admin_engine, empty_conv)

    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Let me look."}, {"retract": "Let me look."})
    r = await _post(client, user_a, conv)
    await wait_for_turns()

    assert r.status_code == empty.status_code
    assert await stored_messages(admin_engine, conv) == empty_stored
    assert sse_events(r.text)[-1] == sse_events(empty.text)[-1]
    assert await streaming_since(admin_engine, conv) is None


REPLY_FAILED = {"error": "reply_failed"}


async def _assert_failed_and_free(client, admin_engine, user, conv, r):
    assert r.status_code == 200
    assert sse_events(r.text)[-1] == REPLY_FAILED
    assert await stored_messages(admin_engine, conv) == [("user", PROMPT)]
    assert await streaming_since(admin_engine, conv) is None

    nxt = await _post(client, user, conv)
    await wait_for_turns()
    assert nxt.status_code != 409
    assert nxt.status_code == 200


async def test_narration_retracted_and_followed_only_by_whitespace_fails_the_reply_stores_nothing_and_frees_the_conversation(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream(
        {"content": "Let me look."},
        {"retract": "Let me look."},
        {"content": "\n\n "},
    )

    r = await _post(client, user_a, conv)
    await wait_for_turns()

    model_stream({"content": "The answer."})
    await _assert_failed_and_free(client, admin_engine, user_a, conv, r)


async def test_narration_retracted_with_nothing_after_it_fails_the_reply_stores_nothing_and_frees_the_conversation(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Let me look."}, {"retract": "Let me look."})

    r = await _post(client, user_a, conv)
    await wait_for_turns()

    model_stream({"content": "The answer."})
    await _assert_failed_and_free(client, admin_engine, user_a, conv, r)


async def test_a_plain_reply_with_no_retract_is_still_stored(
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "The answer."})

    r = await _post(client, user_a, conv)
    await wait_for_turns()

    assert r.status_code == 200
    assert REPLY_FAILED not in sse_events(r.text)
    assert await stored_messages(admin_engine, conv) == [
        ("user", PROMPT),
        ("assistant", "The answer."),
    ]
    assert await streaming_since(admin_engine, conv) is None
