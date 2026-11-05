"""Shared helpers for the chat-path tests: rows read and clock moves through
admin_engine (owner, so RLS never hides a row), turns started as the route
starts them, and the SSE body parser."""

import json

from sqlalchemy import text

import apps.api.chat_service as chat_service
from apps.api import turns
from tests.api.conftest import as_user

PROMPT = "what did I upload?"
DONE = "[DONE]"
FAILED_FRAME = {"error": "reply_failed"}


async def stored_messages(admin_engine, conv) -> list[tuple[str, str]]:
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT role, content FROM messages WHERE conversation_id = :c"
                " ORDER BY created_at, id"
            ),
            {"c": conv},
        )
        return [(role, content) for role, content in rows]


async def streaming_since(admin_engine, conv):
    async with admin_engine.connect() as conn:
        return await conn.scalar(
            text("SELECT streaming_since FROM conversations WHERE id = :c"),
            {"c": conv},
        )


async def age_claim(admin_engine, conv, seconds: int) -> None:
    """Sets the claim to `seconds` before the database's now (0 = held now)."""
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE conversations"
                " SET streaming_since = now() - make_interval(secs => :s)"
                " WHERE id = :c"
            ),
            {"c": conv, "s": seconds},
        )


async def stored_note(admin_engine, user_id) -> list[str]:
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT about FROM user_profiles WHERE user_id = :u"), {"u": user_id}
        )
        return [about for (about,) in rows]


async def user_turn(user, conv, prompt: str = PROMPT):
    """A user turn as `user`; returns (conversation_id, claimed_at)."""
    with as_user(user):
        return await chat_service.persist_user_turn(prompt, conv, user.id)


def start_turn_as(user, conv, claimed_at, stream_fn):
    """Start the reply's turn as `user`, as the route does."""
    with as_user(user):
        return turns.start_turn(stream_fn, [], conv, user.id, claimed_at)


def sse_frames(body: str) -> list[str]:
    """The data payloads of an SSE body, in order."""
    frames = []
    for event in body.split("\n\n"):
        event = event.strip()
        if not event:
            continue
        assert event.startswith("data: "), event
        frames.append(event[len("data: ") :])
    return frames


def sse_events(body: str) -> list[object]:
    """Each frame JSON-decoded, except the literal [DONE]."""
    return [f if f == DONE else json.loads(f) for f in sse_frames(body)]


def sse_contents(events: list[object]) -> list[str]:
    return [e["content"] for e in events if isinstance(e, dict) and "content" in e]


def text_of(content) -> str:
    """A model message's content as plain text: a string, or its text blocks
    joined."""
    if isinstance(content, str):
        return content
    return "".join(block["text"] for block in content if block.get("type") == "text")
