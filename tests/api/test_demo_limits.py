"""A visitor (token with no email) gets the guest prompt with no tools, a
lifetime turn cap checked before anything is persisted, and no uploads.
Members are untouched."""

import pytest
from sqlalchemy import text

import apps.api.routers.chat as chat_router
from packages.core.demo.prompt import DEMO_SYSTEM_PROMPT
from tests.api.conftest import bearer
from tests.api.factories import make_conversation, make_message, make_user


@pytest.fixture
async def visitor(admin_engine):
    async with admin_engine.begin() as conn:
        uid = (
            await conn.execute(text("INSERT INTO users DEFAULT VALUES RETURNING id"))
        ).scalar_one()

    class V:
        id = uid
        email = None

    return V


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


async def test_turn_cap_refuses_before_persisting(
    client, admin_engine, visitor, harness
):
    cid = await make_conversation(admin_engine, visitor.id)
    for i in range(3):
        await make_message(admin_engine, cid, "user", f"q{i}")
    r = await client.post(
        "/api/chat",
        json={"prompt": "one more"},
        headers=bearer(visitor, anonymous=True),
    )
    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "demo_limit"}
    assert harness == []
    assert await _count_messages(admin_engine) == 3


async def test_turn_cap_counts_across_conversations(
    client, admin_engine, visitor, harness, monkeypatch
):
    monkeypatch.setenv("DEMO_TURN_LIMIT", "2")
    for i in range(2):
        cid = await make_conversation(admin_engine, visitor.id)
        await make_message(admin_engine, cid, "user", f"q{i}")
    r = await client.post(
        "/api/chat",
        json={"prompt": "new chat"},
        headers=bearer(visitor, anonymous=True),
    )
    assert r.status_code == 403


async def test_member_has_no_turn_cap(client, admin_engine, user_a, harness):
    cid = await make_conversation(admin_engine, user_a.id)
    for i in range(5):
        await make_message(admin_engine, cid, "user", f"q{i}")
    r = await client.post("/api/chat", json={"prompt": "more"}, headers=bearer(user_a))
    assert r.status_code == 200


async def test_visitor_cannot_upload(client, visitor):
    r = await client.post(
        "/api/documents",
        files={"file": ("x.txt", b"hello", "text/plain")},
        headers=bearer(visitor, anonymous=True),
    )
    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "demo_limit"}


async def test_converted_but_unverified_visitor_is_still_limited(
    client, admin_engine, harness
):
    # Signup writes an email onto the row, but the visitor's cookie still has
    # none: limits key on the token, not the row.
    user = await make_user(admin_engine, "pending@example.com")
    cid = await make_conversation(admin_engine, user.id)
    for i in range(3):
        await make_message(admin_engine, cid, "user", f"q{i}")
    r = await client.post(
        "/api/chat", json={"prompt": "more"}, headers=bearer(user, anonymous=True)
    )
    assert r.status_code == 403
