"""sweep_anonymous_users end to end: an aged visitor goes with everything it
owns (cascade through the RLS-policied tables), a fresh visitor and every
member stay.

Runs through the APP engine (hax_app, RLS on): the cascade is proven under
the real role. Seeds and asserts go through admin_engine."""

import asyncio
import logging

from sqlalchemy import text

import apps.worker.tasks as tasks
from apps.worker.celery_app import celery_app
from packages.core.auth.revocation import sva_cache_key
from packages.db import engine as app_engine
from packages.db.models.chunk import EMBEDDING_DIM
from tests.api.factories import (
    make_chunk,
    make_conversation,
    make_document,
    make_message,
    make_user,
    make_visitor,
)


async def _age(admin_engine, user_id, days: int) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE users SET created_at = now() - make_interval(days => :d)"
                " WHERE id = :id"
            ),
            {"d": days, "id": user_id},
        )


async def _count(admin_engine, table: str, column: str, value) -> int:
    async with admin_engine.connect() as conn:
        row = await conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE {column} = :v"), {"v": value}
        )
        return row.scalar_one()


async def _seed_full_visitor(admin_engine, days: int):
    """A visitor with a conversation, two messages, a document and a chunk."""
    visitor = await make_visitor(admin_engine)
    await _age(admin_engine, visitor.id, days)
    conv = await make_conversation(admin_engine, visitor.id)
    await make_message(admin_engine, conv, "user", "hello")
    await make_message(admin_engine, conv, "assistant", "hi")
    doc = await make_document(admin_engine, visitor.id, storage_key="documents/x")
    await make_chunk(admin_engine, doc, visitor.id, 0, "hello", [0.0] * EMBEDDING_DIM)
    return visitor, conv, doc


async def _owned_rows(admin_engine, visitor, conv, doc) -> dict[str, int]:
    return {
        "users": await _count(admin_engine, "users", "id", visitor.id),
        "conversations": await _count(admin_engine, "conversations", "id", conv),
        "messages": await _count(admin_engine, "messages", "conversation_id", conv),
        "documents": await _count(admin_engine, "documents", "id", doc),
        "chunks": await _count(admin_engine, "chunks", "document_id", doc),
    }


async def test_an_aged_visitor_goes_with_everything_it_owns(admin_engine):
    visitor, conv, doc = await _seed_full_visitor(admin_engine, days=4)
    before = await _owned_rows(admin_engine, visitor, conv, doc)
    assert before == {
        "users": 1,
        "conversations": 1,
        "messages": 2,
        "documents": 1,
        "chunks": 1,
    }

    assert await tasks.sweep_anonymous_users_async() == 1

    assert await _owned_rows(admin_engine, visitor, conv, doc) == {
        "users": 0,
        "conversations": 0,
        "messages": 0,
        "documents": 0,
        "chunks": 0,
    }


async def test_retention_is_configurable(admin_engine, monkeypatch):
    monkeypatch.setenv("ANON_RETENTION_DAYS", "10")
    visitor, conv, doc = await _seed_full_visitor(admin_engine, days=4)

    assert await tasks.sweep_anonymous_users_async() == 0
    assert await _count(admin_engine, "users", "id", visitor.id) == 1


async def test_a_fresh_visitor_is_kept(admin_engine):
    visitor = await make_visitor(admin_engine)
    conv = await make_conversation(admin_engine, visitor.id)

    assert await tasks.sweep_anonymous_users_async() == 0

    assert await _count(admin_engine, "users", "id", visitor.id) == 1
    assert await _count(admin_engine, "conversations", "id", conv) == 1


async def test_a_member_is_never_swept(admin_engine):
    member = await make_user(admin_engine, "old@test.local")
    await _age(admin_engine, member.id, 30)
    conv = await make_conversation(admin_engine, member.id)

    assert await tasks.sweep_anonymous_users_async() == 0

    assert await _count(admin_engine, "users", "id", member.id) == 1
    assert await _count(admin_engine, "conversations", "id", conv) == 1


async def test_the_task_runs_the_sweep_and_beat_names_it(admin_engine, caplog):
    caplog.set_level(logging.INFO)
    visitor, conv, doc = await _seed_full_visitor(admin_engine, days=4)

    # The real task drives its own event loop; off-thread, with the app pool
    # emptied first so that loop never inherits a connection bound to this one.
    await app_engine.dispose()
    await asyncio.to_thread(tasks.sweep_anonymous_users)

    assert await _count(admin_engine, "users", "id", visitor.id) == 0
    assert "swept 1 anonymous users" in caplog.text

    schedule = celery_app.conf.beat_schedule["sweep-anonymous-users"]
    assert schedule["task"] == "sweep_anonymous_users"
    assert "sweep_anonymous_users" in celery_app.tasks
    assert celery_app.conf.timezone == "UTC"


async def test_the_sweep_purges_the_swept_visitors_revocation_cache(
    admin_engine, fake_redis, monkeypatch
):
    monkeypatch.setattr(tasks, "_async_redis", lambda: fake_redis)
    monkeypatch.setattr(fake_redis, "aclose", _noop, raising=False)
    visitor, conv, doc = await _seed_full_visitor(admin_engine, days=4)
    await fake_redis.set(sva_cache_key(visitor.id), "0")

    assert await tasks.sweep_anonymous_users_async() == 1
    assert await fake_redis.get(sva_cache_key(visitor.id)) is None


async def _noop():
    return None
