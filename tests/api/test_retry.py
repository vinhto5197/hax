"""POST /api/conversations/{id}/retry writes a new reply for the question
already stored, without storing the question again. `after` names the user
message whose reply is rewritten; under the claim, the last message decides:
`after` last → write the reply; a reply right after `after` → with
`replace: true` delete it and write a new one, with `replace: false` refuse
409 already_answered; anything else → 409 nothing_to_retry. A refusal deletes
nothing and leaves the conversation free. A visitor's retry counts as a turn.

Every test goes through the route with the model scripted by conftest's
`model_stream`; seeds and asserts go through admin_engine.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
from sqlalchemy import text

import apps.api.chat_service as chat_service
import apps.api.routers.chat as chat_router
from packages.core.schemas.chat import ModelId
from packages.db.user_context import current_user_id
from tests.api.conftest import bearer, wait_for_turns
from tests.api.factories import make_conversation, make_visitor
from tests.api.helpers import (
    DONE,
    FAILED_FRAME,
    age_claim,
    sse_contents,
    sse_events,
    stored_messages,
    streaming_since,
    text_of,
)

pytestmark = pytest.mark.usefixtures("no_background_outlives_its_test")

QUESTION = "what did I upload last week?"
EARLIER_QUESTION = "hello there"
EARLIER_REPLY = "Hi, how can I help?"
OLD_REPLY = "Last week you upl"
NEW_REPLY = "Last week you uploaded two files."
OLD_SOURCES = [{"document_id": str(uuid.uuid4()), "filename": "a.txt"}]


class ProviderBlewUp(Exception):
    pass


class HistoryReadFailed(Exception):
    pass


class _Seeder:
    """Seeds messages with strictly increasing created_at, an hour in the
    past, so a reply written now always sorts last."""

    def __init__(self, admin_engine):
        self.admin_engine = admin_engine
        self.at = datetime.now(UTC) - timedelta(hours=1)

    async def __call__(
        self, conv, role: str, content: str, sources: list | None = None
    ) -> uuid.UUID:
        self.at += timedelta(seconds=1)
        async with self.admin_engine.begin() as conn:
            row = await conn.execute(
                text(
                    "INSERT INTO messages"
                    " (conversation_id, role, content, sources, created_at)"
                    " VALUES (:c, :role, :content, CAST(:sources AS jsonb), :at)"
                    " RETURNING id"
                ),
                {
                    "c": conv,
                    "role": role,
                    "content": content,
                    "sources": None if sources is None else json.dumps(sources),
                    "at": self.at,
                },
            )
            return row.scalar_one()


@pytest.fixture
def seed(admin_engine):
    return _Seeder(admin_engine)


async def _retry(
    client,
    user,
    conv,
    after,
    *,
    replace: bool | None = None,
    model: str | None = None,
    anonymous: bool = False,
):
    body: dict[str, object] = {"after": str(after)}
    if replace is not None:
        body["replace"] = replace
    if model is not None:
        body["model"] = model
    return await client.post(
        f"/api/conversations/{conv}/retry",
        json=body,
        headers=bearer(user, anonymous=anonymous),
    )


async def _rows_with_sources(admin_engine, conv) -> int:
    async with admin_engine.connect() as conn:
        return await conn.scalar(
            text(
                "SELECT count(*) FROM messages"
                " WHERE conversation_id = :c AND sources IS NOT NULL"
            ),
            {"c": conv},
        )


async def _message_exists(admin_engine, message_id) -> bool:
    async with admin_engine.connect() as conn:
        return bool(
            await conn.scalar(
                text("SELECT count(*) FROM messages WHERE id = :m"), {"m": message_id}
            )
        )


# --- writing the reply -------------------------------------------------------


async def test_a_retry_streams_a_reply_and_stores_one_assistant_message_after_the_existing_user_message(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_a.id)
    q = await seed(conv, "user", QUESTION)
    model_stream({"content": "Last week "}, {"content": "you uploaded two files."})

    r = await _retry(client, user_a, conv, q)
    await wait_for_turns()

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    assert sse_contents(events) == ["Last week ", "you uploaded two files."]
    assert events[-1] == DONE
    assert await stored_messages(admin_engine, conv) == [
        ("user", QUESTION),
        ("assistant", NEW_REPLY),
    ]
    assert await _message_exists(admin_engine, q)
    assert await streaming_since(admin_engine, conv) is None


async def test_a_retry_gives_the_model_the_question_once_as_the_last_message(
    client, admin_engine, user_a, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_a.id)
    await seed(conv, "user", EARLIER_QUESTION)
    await seed(conv, "assistant", EARLIER_REPLY)
    q = await seed(conv, "user", QUESTION)
    calls = model_stream({"content": NEW_REPLY})

    await _retry(client, user_a, conv, q)
    await wait_for_turns()

    assert len(calls) == 1
    history = calls[0]
    assert [(m["role"], text_of(m["content"])) for m in history] == [
        ("user", EARLIER_QUESTION),
        ("assistant", EARLIER_REPLY),
        ("user", QUESTION),
    ]


async def test_a_regenerate_gives_the_model_the_question_once_and_never_the_replaced_reply(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_a.id)
    await seed(conv, "user", EARLIER_QUESTION)
    await seed(conv, "assistant", EARLIER_REPLY)
    q = await seed(conv, "user", QUESTION)
    await seed(conv, "assistant", OLD_REPLY)
    calls = model_stream({"content": NEW_REPLY})

    await _retry(client, user_a, conv, q, replace=True)
    await wait_for_turns()

    assert len(calls) == 1
    assert [(m["role"], text_of(m["content"])) for m in calls[0]] == [
        ("user", EARLIER_QUESTION),
        ("assistant", EARLIER_REPLY),
        ("user", QUESTION),
    ]


async def test_a_members_retry_uses_the_model_named_in_the_request(
    client, admin_engine, user_a, monkeypatch, seed
):
    calls: list[dict] = []

    async def fake(messages, **kwargs):
        calls.append(kwargs)
        yield {"content": "ok"}

    monkeypatch.setattr(chat_router, "stream_completion_agentic", fake)
    model = next(m for m in get_args(ModelId) if m != chat_router.DEFAULT_MODEL)
    conv = await make_conversation(admin_engine, user_a.id)
    q = await seed(conv, "user", QUESTION)

    r = await _retry(client, user_a, conv, q, model=model)
    await wait_for_turns()

    assert r.status_code == 200
    assert calls[0]["model"] == model


# --- regenerate: the replace flag ---------------------------------------------


async def test_a_regenerate_deletes_the_reply_with_its_sources_and_stores_the_new_one(
    client, admin_engine, user_a, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_a.id)
    q = await seed(conv, "user", QUESTION)
    old = await seed(conv, "assistant", OLD_REPLY, sources=OLD_SOURCES)
    model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, conv, q, replace=True)
    await wait_for_turns()

    assert r.status_code == 200
    assert sse_events(r.text)[-1] == DONE
    assert not await _message_exists(admin_engine, old)
    assert await stored_messages(admin_engine, conv) == [
        ("user", QUESTION),
        ("assistant", NEW_REPLY),
    ]
    assert await _rows_with_sources(admin_engine, conv) == 0
    assert await streaming_since(admin_engine, conv) is None


async def test_a_reply_after_after_without_replace_is_refused_409_already_answered_and_kept(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_a.id)
    q = await seed(conv, "user", QUESTION)
    old = await seed(conv, "assistant", OLD_REPLY, sources=OLD_SOURCES)
    calls = model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, conv, q, replace=False)

    assert r.status_code == 409
    assert r.json() == {"detail": "already_answered"}
    assert calls == []
    assert await _message_exists(admin_engine, old)
    assert await stored_messages(admin_engine, conv) == [
        ("user", QUESTION),
        ("assistant", OLD_REPLY),
    ]
    assert await _rows_with_sources(admin_engine, conv) == 1
    assert await streaming_since(admin_engine, conv) is None


async def test_replace_defaults_to_false_so_a_reply_after_after_is_refused_409_already_answered(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_a.id)
    q = await seed(conv, "user", QUESTION)
    await seed(conv, "assistant", OLD_REPLY)
    model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, conv, q)

    assert r.status_code == 409
    assert r.json() == {"detail": "already_answered"}
    assert await stored_messages(admin_engine, conv) == [
        ("user", QUESTION),
        ("assistant", OLD_REPLY),
    ]


async def test_replace_true_with_after_already_last_writes_the_reply(
    client, admin_engine, user_a, model_stream, seed
):
    # The reply the page showed vanished meanwhile: nothing to delete.
    conv = await make_conversation(admin_engine, user_a.id)
    q = await seed(conv, "user", QUESTION)
    model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, conv, q, replace=True)
    await wait_for_turns()

    assert r.status_code == 200
    assert sse_events(r.text)[-1] == DONE
    assert await stored_messages(admin_engine, conv) == [
        ("user", QUESTION),
        ("assistant", NEW_REPLY),
    ]


async def test_a_regenerate_whose_reply_fails_leaves_the_question_last_with_no_assistant_message(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_a.id)
    q = await seed(conv, "user", QUESTION)
    await seed(conv, "assistant", OLD_REPLY, sources=OLD_SOURCES)
    model_stream({"content": "Last "}, error=ProviderBlewUp("boom"))

    r = await _retry(client, user_a, conv, q, replace=True)
    await wait_for_turns()

    assert r.status_code == 200
    events = sse_events(r.text)
    assert events[-1] == FAILED_FRAME
    assert DONE not in events
    assert await stored_messages(admin_engine, conv) == [("user", QUESTION)]
    assert await streaming_since(admin_engine, conv) is None


# --- nothing to retry: the end is not what the page saw -----------------------


async def test_a_retry_on_a_conversation_with_no_messages_is_refused_409_nothing_to_retry(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream
):
    conv = await make_conversation(admin_engine, user_a.id)
    calls = model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, conv, uuid.uuid4(), replace=True)

    assert r.status_code == 409
    assert r.json() == {"detail": "nothing_to_retry"}
    assert calls == []
    assert await stored_messages(admin_engine, conv) == []
    assert await streaming_since(admin_engine, conv) is None


async def test_a_retry_whose_after_is_not_the_last_user_message_is_refused_409_nothing_to_retry(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream, seed
):
    # A newer question than the page saw is last.
    conv = await make_conversation(admin_engine, user_a.id)
    older = await seed(conv, "user", EARLIER_QUESTION)
    await seed(conv, "assistant", EARLIER_REPLY)
    await seed(conv, "user", QUESTION)
    calls = model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, conv, older, replace=True)

    assert r.status_code == 409
    assert r.json() == {"detail": "nothing_to_retry"}
    assert calls == []
    assert await stored_messages(admin_engine, conv) == [
        ("user", EARLIER_QUESTION),
        ("assistant", EARLIER_REPLY),
        ("user", QUESTION),
    ]
    assert await streaming_since(admin_engine, conv) is None


async def test_a_regenerate_whose_after_is_older_than_the_last_turn_deletes_nothing_and_is_refused_409_nothing_to_retry(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream, seed
):
    # A stale page asks to replace the reply to an older question; the reply
    # stored last belongs to a newer question it never showed.
    conv = await make_conversation(admin_engine, user_a.id)
    older = await seed(conv, "user", EARLIER_QUESTION)
    await seed(conv, "assistant", EARLIER_REPLY)
    await seed(conv, "user", QUESTION)
    newest = await seed(conv, "assistant", NEW_REPLY, sources=OLD_SOURCES)
    calls = model_stream({"content": "something else"})

    r = await _retry(client, user_a, conv, older, replace=True)

    assert r.status_code == 409
    assert r.json() == {"detail": "nothing_to_retry"}
    assert calls == []
    assert await _message_exists(admin_engine, newest)
    assert await stored_messages(admin_engine, conv) == [
        ("user", EARLIER_QUESTION),
        ("assistant", EARLIER_REPLY),
        ("user", QUESTION),
        ("assistant", NEW_REPLY),
    ]
    assert await _rows_with_sources(admin_engine, conv) == 1
    assert await streaming_since(admin_engine, conv) is None


async def test_a_retry_whose_after_belongs_to_another_conversation_is_refused_409_nothing_to_retry(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_a.id)
    other = await make_conversation(admin_engine, user_a.id)
    await seed(conv, "user", QUESTION)
    elsewhere = await seed(other, "user", EARLIER_QUESTION)
    calls = model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, conv, elsewhere)

    assert r.status_code == 409
    assert r.json() == {"detail": "nothing_to_retry"}
    assert calls == []
    assert await stored_messages(admin_engine, conv) == [("user", QUESTION)]
    assert await stored_messages(admin_engine, other) == [("user", EARLIER_QUESTION)]
    assert await streaming_since(admin_engine, conv) is None


async def test_a_regenerate_whose_after_belongs_to_another_conversation_deletes_nothing(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_a.id)
    other = await make_conversation(admin_engine, user_a.id)
    await seed(conv, "user", QUESTION)
    reply = await seed(conv, "assistant", OLD_REPLY)
    elsewhere = await seed(other, "user", EARLIER_QUESTION)
    model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, conv, elsewhere, replace=True)

    assert r.status_code == 409
    assert r.json() == {"detail": "nothing_to_retry"}
    assert await _message_exists(admin_engine, reply)
    assert await stored_messages(admin_engine, conv) == [
        ("user", QUESTION),
        ("assistant", OLD_REPLY),
    ]


# --- the claim, ownership, the demo cap ---------------------------------------


async def test_a_retry_while_a_reply_holds_the_claim_is_refused_409_turn_in_progress_and_deletes_nothing(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, user_a, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_a.id)
    q = await seed(conv, "user", QUESTION)
    await seed(conv, "assistant", OLD_REPLY)
    await age_claim(admin_engine, conv, 0)
    calls = model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, conv, q, replace=True)

    assert r.status_code == 409
    assert r.json() == {"detail": chat_service.TURN_IN_PROGRESS}
    assert calls == []
    assert await stored_messages(admin_engine, conv) == [
        ("user", QUESTION),
        ("assistant", OLD_REPLY),
    ]


async def test_a_retry_on_another_users_conversation_is_404_and_touches_nothing(
    client, admin_engine, user_a, user_b, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_b.id)
    q = await seed(conv, "user", QUESTION)
    await seed(conv, "assistant", OLD_REPLY)
    calls = model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, conv, q, replace=True)

    assert r.status_code == 404
    assert calls == []
    assert await stored_messages(admin_engine, conv) == [
        ("user", QUESTION),
        ("assistant", OLD_REPLY),
    ]
    assert await streaming_since(admin_engine, conv) is None


async def test_a_retry_on_a_conversation_that_does_not_exist_is_404(
    client, user_a, model_stream
):
    model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, uuid.uuid4(), uuid.uuid4())

    assert r.status_code == 404


async def test_a_visitors_retry_counts_as_a_turn_and_a_visitor_over_the_cap_is_refused_403_demo_limit(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, model_stream, seed, monkeypatch
):
    monkeypatch.setenv("DEMO_TURN_LIMIT", "1")
    visitor = await make_visitor(admin_engine)
    conv = await make_conversation(admin_engine, visitor.id)
    q = await seed(conv, "user", QUESTION)
    calls = model_stream({"content": "Last "}, error=ProviderBlewUp("boom"))

    first = await _retry(client, visitor, conv, q, anonymous=True)
    await wait_for_turns()
    assert first.status_code == 200
    assert len(calls) == 1

    r = await _retry(client, visitor, conv, q, anonymous=True)

    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "demo_limit"}
    assert len(calls) == 1
    assert await stored_messages(admin_engine, conv) == [("user", QUESTION)]
    assert await streaming_since(admin_engine, conv) is None


async def test_a_visitor_over_the_cap_is_refused_403_before_a_regenerate_deletes_anything(  # noqa: E501 — the name is the behaviour line
    client, admin_engine, model_stream, seed, monkeypatch
):
    monkeypatch.setenv("DEMO_TURN_LIMIT", "1")
    visitor = await make_visitor(admin_engine)
    conv = await make_conversation(admin_engine, visitor.id)
    q = await seed(conv, "user", QUESTION)
    calls = model_stream({"content": NEW_REPLY})
    first = await _retry(client, visitor, conv, q, anonymous=True)
    await wait_for_turns()
    assert first.status_code == 200

    r = await _retry(client, visitor, conv, q, replace=True, anonymous=True)

    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "demo_limit"}
    assert len(calls) == 1
    assert await stored_messages(admin_engine, conv) == [
        ("user", QUESTION),
        ("assistant", NEW_REPLY),
    ]


@pytest.mark.parametrize("refusal", ["nothing_to_retry", "already_answered"])
async def test_a_visitors_retry_refused_409_still_spends_a_turn(
    client, admin_engine, model_stream, seed, monkeypatch, refusal
):
    monkeypatch.setenv("DEMO_TURN_LIMIT", "1")
    visitor = await make_visitor(admin_engine)
    conv = await make_conversation(admin_engine, visitor.id)
    q = await seed(conv, "user", QUESTION)
    if refusal == "already_answered":
        await seed(conv, "assistant", OLD_REPLY)
        after = q
    else:
        after = uuid.uuid4()
    calls = model_stream({"content": NEW_REPLY})

    refused = await _retry(client, visitor, conv, after, anonymous=True)
    assert refused.status_code == 409
    assert refused.json()["detail"] == refusal

    r = await _retry(client, visitor, conv, q, replace=True, anonymous=True)

    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "demo_limit"}
    assert calls == []


# --- a failure before the turn starts -----------------------------------------


async def test_a_failure_before_the_turn_starts_releases_the_claim(
    raw_client, admin_engine, user_a, model_stream, seed, monkeypatch
):
    async def boom(*args, **kwargs):
        raise HistoryReadFailed()

    monkeypatch.setattr(chat_router, "load_history", boom)
    conv = await make_conversation(admin_engine, user_a.id)
    q = await seed(conv, "user", QUESTION)
    calls = model_stream({"content": NEW_REPLY})

    r = await _retry(raw_client, user_a, conv, q)

    assert r.status_code >= 500
    assert calls == []
    assert await streaming_since(admin_engine, conv) is None
    assert await stored_messages(admin_engine, conv) == [("user", QUESTION)]


# --- a lapsed turn saving late --------------------------------------------------


async def test_a_lapsed_turn_saving_after_a_retry_took_its_claim_stores_nothing(
    client, admin_engine, user_a, model_stream, seed
):
    conv = await make_conversation(admin_engine, user_a.id)
    q = await seed(conv, "user", QUESTION)
    async with admin_engine.begin() as conn:
        stale_claim = await conn.scalar(
            text(
                "UPDATE conversations"
                " SET streaming_since = now() - interval '3 minutes'"
                " WHERE id = :c RETURNING streaming_since"
            ),
            {"c": conv},
        )
    model_stream({"content": NEW_REPLY})

    r = await _retry(client, user_a, conv, q)
    await wait_for_turns()
    assert r.status_code == 200

    token = current_user_id.set(user_a.id)
    try:
        await chat_service.persist_assistant_turn(
            conv, user_a.id, OLD_REPLY, claimed_at=stale_claim
        )
    finally:
        current_user_id.reset(token)

    assert await stored_messages(admin_engine, conv) == [
        ("user", QUESTION),
        ("assistant", NEW_REPLY),
    ]
