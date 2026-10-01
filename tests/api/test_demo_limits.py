"""A visitor (token with no email) gets the guest prompt with no tools, a
lifetime turn cap checked before anything is persisted, and no uploads.
Members are untouched."""

import asyncio

import pytest
from sqlalchemy import text

import apps.api.routers.chat as chat_router
from packages.core.demo.prompt import DEMO_SYSTEM_PROMPT
from tests.api.conftest import bearer
from tests.api.factories import (
    make_conversation,
    make_user,
    make_visitor,
)


@pytest.fixture
async def visitor(admin_engine):
    return await make_visitor(admin_engine)


@pytest.fixture
def harness(monkeypatch):
    """Records each harness call's keyword arguments; streams nothing."""
    calls: list[dict] = []

    async def fake(messages, **kwargs):
        calls.append(kwargs)
        if False:
            yield {}

    monkeypatch.setattr(chat_router, "stream_completion_agentic", fake)
    return calls


async def _first_conversation_id(admin_engine, user_id):
    async with admin_engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT id FROM conversations WHERE user_id = :u LIMIT 1"),
                {"u": user_id},
            )
        ).scalar_one()


async def _count_messages(admin_engine):
    async with admin_engine.connect() as conn:
        return (await conn.execute(text("SELECT count(*) FROM messages"))).scalar_one()


async def test_visitor_gets_the_guest_prompt_and_no_tools(client, visitor, harness):
    r = await client.post(
        "/api/chat", json={"prompt": "hi"}, headers=bearer(visitor, anonymous=True)
    )
    assert r.status_code == 200
    assert harness[0]["system"] == DEMO_SYSTEM_PROMPT
    assert harness[0]["tools"] is False


async def test_visitor_model_choice_is_ignored(client, visitor, harness):
    r = await client.post(
        "/api/chat",
        json={"prompt": "hi", "model": "claude-opus-4-8"},
        headers=bearer(visitor, anonymous=True),
    )
    assert r.status_code == 200
    assert harness[0]["model"] == chat_router.DEFAULT_MODEL


async def test_member_gets_the_agentic_prompt_and_tools(client, user_a, harness):
    r = await client.post("/api/chat", json={"prompt": "hi"}, headers=bearer(user_a))
    assert r.status_code == 200
    assert harness[0]["system"] == chat_router.AGENTIC_SYSTEM
    assert harness[0]["tools"] is True


def _send(client, user, prompt="hi", **extra):
    return client.post(
        "/api/chat",
        json={"prompt": prompt, **extra},
        headers=bearer(user, anonymous=True),
    )


async def test_turn_cap_refuses_the_turn_after_the_limit(
    client, admin_engine, visitor, harness
):
    for i in range(3):
        assert (await _send(client, visitor, f"q{i}")).status_code == 200
    r = await _send(client, visitor, "one more")
    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "demo_limit"}
    # Refused before anything was persisted.
    assert len(harness) == 3
    assert await _count_messages(admin_engine) == 3


async def test_turn_cap_counts_across_conversations(
    client, visitor, harness, monkeypatch
):
    # Each send without a conversation id starts a new conversation.
    monkeypatch.setenv("DEMO_TURN_LIMIT", "2")
    assert (await _send(client, visitor, "a")).status_code == 200
    assert (await _send(client, visitor, "b")).status_code == 200
    assert (await _send(client, visitor, "c")).status_code == 403


async def test_deleting_a_conversation_does_not_refund_turns(
    client, admin_engine, visitor, harness
):
    assert (await _send(client, visitor, "q0")).status_code == 200
    cid = await _first_conversation_id(admin_engine, visitor.id)
    for i in (1, 2):
        r = await _send(client, visitor, f"q{i}", conversation_id=str(cid))
        assert r.status_code == 200
    # Deleting is allowed; the turns are counted, not the rows.
    r = await client.delete(
        f"/api/conversations/{cid}", headers=bearer(visitor, anonymous=True)
    )
    assert r.status_code == 204
    assert await _count_messages(admin_engine) == 0
    assert (await _send(client, visitor, "again")).status_code == 403


async def test_concurrent_sends_cannot_exceed_the_cap(client, visitor, harness):
    results = await asyncio.gather(*(_send(client, visitor, f"q{i}") for i in range(8)))
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 200, 200, 403, 403, 403, 403, 403]
    assert len(harness) == 3


async def test_member_has_no_turn_cap(client, admin_engine, user_a, harness):
    for i in range(5):
        assert (
            await client.post(
                "/api/chat", json={"prompt": f"q{i}"}, headers=bearer(user_a)
            )
        ).status_code == 200


async def test_member_can_still_delete(client, admin_engine, user_a):
    cid = await make_conversation(admin_engine, user_a.id)
    r = await client.delete(f"/api/conversations/{cid}", headers=bearer(user_a))
    assert r.status_code == 204


async def test_visitor_cannot_upload(client, visitor):
    r = await client.post(
        "/api/documents",
        files={"file": ("x.txt", b"hello", "text/plain")},
        headers=bearer(visitor, anonymous=True),
    )
    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "demo_limit"}


async def test_limits_key_on_the_token_not_the_row(client, admin_engine, harness):
    # A row with an email presented through a token without one is a visitor
    # to every limit: the token is the only marker read.
    user = await make_user(admin_engine, "member@example.com")
    for i in range(3):
        assert (await _send(client, user, f"q{i}")).status_code == 200
    assert (await _send(client, user, "more")).status_code == 403
