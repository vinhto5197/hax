"""A model failure mid-reply is reported, never saved as complete: the route
streams what arrived, then a `reply_failed` frame and no `[DONE]`; no
assistant message is stored; the claim is released so the next turn is
accepted; the exception's text stays out of the response and the log. After
a failed turn, a resend gives the model one user turn holding both messages.

Every test goes through POST /api/chat with the model scripted by conftest's
`model_stream`; seeds and asserts go through admin_engine.
"""

import asyncio
import logging
from datetime import timedelta

import pytest

import apps.api.chat_service as chat_service
from packages.db.repos import conversations as conversations_repo
from tests.api.conftest import bearer, wait_for_turns
from tests.api.factories import make_conversation
from tests.api.helpers import (
    DONE,
    FAILED_FRAME,
    sse_contents,
    sse_events,
    stored_messages,
    streaming_since,
    text_of,
)

pytestmark = pytest.mark.usefixtures("no_background_outlives_its_test")

FIRST = "what did I upload last week?"
SECOND = "and the week before?"
THIRD = "anything at all?"
LEAK = "provider echoed the prompt: what did I upload last week?"


class ProviderBlewUp(Exception):
    """A distinctive type name, so the log assertion cannot match by chance."""


class DatabaseDown(Exception):
    pass


async def _post(client, user, conv, prompt: str):
    return await client.post(
        "/api/chat",
        json={"prompt": prompt, "conversation_id": str(conv)},
        headers=bearer(user),
    )


async def test_a_model_error_mid_reply_sends_the_streamed_pieces_then_reply_failed_and_no_done(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Hello "}, {"content": "wor"}, error=ProviderBlewUp(LEAK))

    r = await _post(client, user_a, conv, FIRST)

    assert r.status_code == 200
    events = sse_events(r.text)
    assert DONE not in events
    assert sse_contents(events) == ["Hello ", "wor"]
    assert events[-1] == FAILED_FRAME
    assert events.count(FAILED_FRAME) == 1
    # The frame follows both pieces.
    last_piece = max(
        i for i, e in enumerate(events) if isinstance(e, dict) and "content" in e
    )
    assert events.index(FAILED_FRAME) > last_piece


async def test_a_model_error_mid_reply_stores_the_user_message_and_no_assistant_message(
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Hello "}, {"content": "wor"}, error=ProviderBlewUp(LEAK))

    await _post(client, user_a, conv, FIRST)

    assert await stored_messages(admin_engine, conv) == [("user", FIRST)]


async def test_a_model_error_mid_reply_releases_the_conversation(
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Hello "}, error=ProviderBlewUp(LEAK))

    await _post(client, user_a, conv, FIRST)

    assert await streaming_since(admin_engine, conv) is None


async def test_a_model_errors_text_appears_nowhere_in_the_response_or_the_log(
    client, admin_engine, user_a, model_stream, caplog
):
    caplog.set_level(logging.DEBUG)
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Hello "}, error=ProviderBlewUp(LEAK))

    r = await _post(client, user_a, conv, FIRST)

    assert LEAK not in r.text
    assert "provider echoed" not in r.text
    assert "ProviderBlewUp" not in r.text
    assert LEAK not in caplog.text
    assert "provider echoed" not in caplog.text


async def test_a_model_errors_type_name_is_logged_with_the_conversation_id(
    client, admin_engine, user_a, model_stream, caplog
):
    caplog.set_level(logging.DEBUG)
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Hello "}, error=ProviderBlewUp(LEAK))

    await _post(client, user_a, conv, FIRST)

    assert any(
        "ProviderBlewUp" in record.getMessage() and str(conv) in record.getMessage()
        for record in caplog.records
    ), caplog.text


async def test_a_second_turn_right_after_a_model_error_is_accepted(
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Hello "}, error=ProviderBlewUp(LEAK))
    await _post(client, user_a, conv, FIRST)

    model_stream({"content": "Fine "}, {"content": "now."})
    r = await _post(client, user_a, conv, SECOND)

    assert r.status_code == 200
    assert sse_events(r.text)[-1] == DONE
    assert await stored_messages(admin_engine, conv) == [
        ("user", FIRST),
        ("user", SECOND),
        ("assistant", "Fine now."),
    ]


async def test_a_model_error_before_any_content_sends_reply_failed_and_no_done(
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream(error=ProviderBlewUp(LEAK))

    r = await _post(client, user_a, conv, FIRST)

    assert r.status_code == 200
    events = sse_events(r.text)
    assert DONE not in events
    assert sse_contents(events) == []
    assert events[-1] == FAILED_FRAME
    assert LEAK not in r.text


async def test_a_model_error_before_any_content_stores_no_assistant_message_and_frees_the_conversation(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream(error=ProviderBlewUp(LEAK))
    await _post(client, user_a, conv, FIRST)

    assert await stored_messages(admin_engine, conv) == [("user", FIRST)]
    assert await streaming_since(admin_engine, conv) is None
    model_stream({"content": "ok"})
    again = await _post(client, user_a, conv, SECOND)
    assert again.status_code == 200


async def test_a_clean_stream_still_ends_with_done_and_stores_the_reply(
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Hello "}, {"content": "world."})

    r = await _post(client, user_a, conv, FIRST)

    assert r.status_code == 200
    events = sse_events(r.text)
    assert events[-1] == DONE
    assert FAILED_FRAME not in events
    assert sse_contents(events) == ["Hello ", "world."]
    assert await stored_messages(admin_engine, conv) == [
        ("user", FIRST),
        ("assistant", "Hello world."),
    ]
    assert await streaming_since(admin_engine, conv) is None


async def test_a_resend_after_a_failed_turn_gives_the_model_one_user_turn_holding_both_messages(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Hel"}, error=ProviderBlewUp(LEAK))
    await _post(client, user_a, conv, FIRST)

    calls = model_stream({"content": "ok"})
    await _post(client, user_a, conv, SECOND)

    given = calls[-1]
    assert [m["role"] for m in given] == ["user"]
    assert text_of(given[0]["content"]) == f"{FIRST}\n\n{SECOND}"


async def test_the_model_is_never_given_two_consecutive_turns_with_the_same_role(
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "First answer."})
    await _post(client, user_a, conv, FIRST)
    model_stream({"content": "Hel"}, error=ProviderBlewUp(LEAK))
    await _post(client, user_a, conv, SECOND)
    model_stream(error=ProviderBlewUp(LEAK))
    await _post(client, user_a, conv, THIRD)

    calls = model_stream({"content": "ok"})
    await _post(client, user_a, conv, "last one")

    given = calls[-1]
    roles = [m["role"] for m in given]
    assert roles == ["user", "assistant", "user"]
    assert text_of(given[0]["content"]) == FIRST
    assert text_of(given[1]["content"]) == "First answer."
    assert text_of(given[2]["content"]) == f"{SECOND}\n\n{THIRD}\n\nlast one"


async def test_a_failed_release_after_a_model_error_still_ends_with_reply_failed_and_the_claim_lapses_within_turn_window(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream, monkeypatch
):
    window = timedelta(seconds=1.5)
    monkeypatch.setattr(conversations_repo, "TURN_WINDOW", window)
    conv = await make_conversation(admin_engine, user_a.id)
    model_stream({"content": "Hello "}, error=ProviderBlewUp(LEAK))
    releases: list[object] = []

    async def release(conversation_id, claimed_at):
        releases.append(conversation_id)
        raise DatabaseDown()

    monkeypatch.setattr(chat_service, "release_claim", release)

    r = await _post(client, user_a, conv, FIRST)
    await wait_for_turns()

    events = sse_events(r.text)
    assert events[-1] == FAILED_FRAME
    assert DONE not in events
    assert releases == [conv]
    assert await stored_messages(admin_engine, conv) == [("user", FIRST)]
    assert (await _post(client, user_a, conv, SECOND)).status_code == 409

    await asyncio.sleep(window.total_seconds())
    model_stream({"content": "ok"})
    r = await _post(client, user_a, conv, SECOND)

    assert r.status_code == 200
    assert sse_events(r.text)[-1] == DONE
