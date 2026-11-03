"""sweep_email_tokens end to end: a link that can no longer be used (spent,
voided by a newer link, or expired) loses its row; a live link keeps it.

Runs through the APP engine (hax_app, RLS on, no announced identity):
email_tokens is outside RLS and the app role may delete from it. Seeds and
asserts go through admin_engine."""

import asyncio
import logging

from celery.schedules import crontab
from sqlalchemy import text

import apps.worker.tasks as tasks
from apps.worker.celery_app import celery_app
from packages.core.auth.email_tokens import hash_token
from packages.db import AsyncSessionLocal
from packages.db import engine as app_engine
from packages.db.repos import email_tokens
from packages.db.user_context import current_user_id
from tests.api.factories import make_email_token, make_user

EXPIRED = -60  # seconds: a negative TTL seeds a row that expired a minute ago


async def _exists(admin_engine, token_hash: str) -> bool:
    async with admin_engine.connect() as conn:
        row = await conn.execute(
            text("SELECT count(*) FROM email_tokens WHERE token_hash = :h"),
            {"h": token_hash},
        )
        return row.scalar_one() == 1


async def _total(admin_engine) -> int:
    async with admin_engine.connect() as conn:
        row = await conn.execute(text("SELECT count(*) FROM email_tokens"))
        return row.scalar_one()


async def test_a_spent_token_is_swept(admin_engine):
    u = await make_user(admin_engine, "spent@test.local")
    h = hash_token("spent")
    await make_email_token(admin_engine, u.id, "verify_email", h, used=True)

    assert await tasks.sweep_email_tokens_async() == 1

    assert not await _exists(admin_engine, h)


async def test_an_expired_unused_token_is_swept(admin_engine):
    u = await make_user(admin_engine, "expired@test.local")
    h = hash_token("expired")
    await make_email_token(
        admin_engine, u.id, "reset_password", h, expires_in_s=EXPIRED
    )

    assert await tasks.sweep_email_tokens_async() == 1

    assert not await _exists(admin_engine, h)


async def test_a_live_token_is_kept(admin_engine):
    u = await make_user(admin_engine, "live@test.local")
    h = hash_token("live")
    await make_email_token(admin_engine, u.id, "verify_email", h)

    assert await tasks.sweep_email_tokens_async() == 0

    assert await _exists(admin_engine, h)


async def test_only_dead_tokens_go_when_live_and_dead_rows_share_a_user(
    admin_engine,
):
    u = await make_user(admin_engine, "both@test.local")
    voided = hash_token("older")
    live = hash_token("newer")
    await make_email_token(admin_engine, u.id, "reset_password", voided, used=True)
    await make_email_token(admin_engine, u.id, "reset_password", live)

    assert await tasks.sweep_email_tokens_async() == 1

    assert not await _exists(admin_engine, voided)
    assert await _exists(admin_engine, live)


async def test_the_sweep_runs_in_batches_until_none_remain(admin_engine, monkeypatch):
    monkeypatch.setattr(tasks, "TOKEN_SWEEP_BATCH", 2)
    u = await make_user(admin_engine, "many@test.local")
    for i in range(5):
        await make_email_token(
            admin_engine,
            u.id,
            "verify_email",
            hash_token(f"dead-{i}"),
            expires_in_s=EXPIRED if i % 2 else 3600,
            used=not i % 2,
        )

    real_delete_dead = email_tokens.delete_dead
    limits: list[int] = []
    left_before_each_call: list[int] = []

    async def spy(session, *, limit):
        limits.append(limit)
        left_before_each_call.append(await _total(admin_engine))
        return await real_delete_dead(session, limit=limit)

    monkeypatch.setattr(email_tokens, "delete_dead", spy)

    assert await tasks.sweep_email_tokens_async() == 5

    assert await _total(admin_engine) == 0
    assert limits == [2, 2, 2]
    # Seen from another connection: each batch was committed before the next.
    assert left_before_each_call == [5, 3, 1]


async def test_delete_dead_removes_at_most_limit_rows(admin_engine):
    u = await make_user(admin_engine, "limit@test.local")
    for i in range(3):
        await make_email_token(
            admin_engine, u.id, "verify_email", hash_token(f"d-{i}"), used=True
        )

    async with AsyncSessionLocal() as session:
        deleted = await email_tokens.delete_dead(session, limit=2)
        await session.commit()

    assert deleted == 2
    assert await _total(admin_engine) == 1


async def test_expiry_is_judged_by_the_database_clock(admin_engine):
    u = await make_user(admin_engine, "clock@test.local")
    h = hash_token("one-second-left")
    await make_email_token(admin_engine, u.id, "verify_email", h, expires_in_s=1)

    async with AsyncSessionLocal() as session:
        # The transaction's now() is fixed here, before the link expires; the
        # wall clock passes the expiry during the sleep.
        await session.execute(text("SELECT now()"))
        await asyncio.sleep(1.5)
        deleted = await email_tokens.delete_dead(session, limit=10)
        await session.commit()

    assert deleted == 0
    assert await _exists(admin_engine, h)


async def test_a_link_expiring_at_this_instant_is_dead(admin_engine):
    u = await make_user(admin_engine, "boundary@test.local")
    h = hash_token("expires-now")

    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO email_tokens"
                " (user_id, purpose, token_hash, expires_at)"
                " VALUES (:uid, 'verify_email', :h, now())"
            ),
            {"uid": u.id, "h": h},
        )
        deleted = await email_tokens.delete_dead(session, limit=10)
        await session.commit()

    assert deleted == 1
    assert not await _exists(admin_engine, h)


async def test_a_row_locked_by_another_transaction_is_skipped_not_waited_on(
    admin_engine,
):
    u = await make_user(admin_engine, "locked@test.local")
    held = hash_token("held")
    await make_email_token(
        admin_engine, u.id, "reset_password", held, expires_in_s=EXPIRED
    )
    others = [hash_token(f"free-{i}") for i in range(2)]
    for h in others:
        await make_email_token(
            admin_engine, u.id, "verify_email", h, expires_in_s=EXPIRED
        )

    async with admin_engine.connect() as holder:
        await holder.begin()
        await holder.execute(
            text("SELECT id FROM email_tokens WHERE token_hash = :h FOR UPDATE"),
            {"h": held},
        )
        # Well under the app connection's 5 s lock_timeout: a sweep that waits
        # on the held row trips this, not the database's own timeout.
        deleted = await asyncio.wait_for(tasks.sweep_email_tokens_async(), 2)
        await holder.rollback()

    assert deleted == 2
    assert await _exists(admin_engine, held)
    for h in others:
        assert not await _exists(admin_engine, h)


async def test_the_sweep_needs_no_announced_user(admin_engine):
    assert current_user_id.get() is None
    a = await make_user(admin_engine, "a@test.local")
    b = await make_user(admin_engine, "b@test.local")
    ha, hb = hash_token("of-a"), hash_token("of-b")
    await make_email_token(admin_engine, a.id, "verify_email", ha, used=True)
    await make_email_token(
        admin_engine, b.id, "reset_password", hb, expires_in_s=EXPIRED
    )

    assert await tasks.sweep_email_tokens_async() == 2

    assert not await _exists(admin_engine, ha)
    assert not await _exists(admin_engine, hb)


async def test_the_task_logs_the_count_only_and_beat_schedules_it(admin_engine, caplog):
    caplog.set_level(logging.INFO)
    u = await make_user(admin_engine, "logged@test.local")
    spent, expired = hash_token("log-spent"), hash_token("log-expired")
    await make_email_token(admin_engine, u.id, "verify_email", spent, used=True)
    await make_email_token(
        admin_engine, u.id, "reset_password", expired, expires_in_s=EXPIRED
    )

    # The real task drives its own event loop; off-thread, with the app pool
    # emptied first so that loop never inherits a connection bound to this one.
    await app_engine.dispose()
    await asyncio.to_thread(tasks.sweep_email_tokens)

    assert await _total(admin_engine) == 0
    assert "swept 2 email tokens" in caplog.text
    for secret in (spent, expired, str(u.id), u.email):
        assert secret not in caplog.text

    schedule = celery_app.conf.beat_schedule["sweep-email-tokens"]
    assert schedule["task"] == "sweep_email_tokens"
    assert schedule["schedule"] == crontab(hour=4, minute=30)
    assert "sweep_email_tokens" in celery_app.tasks
    assert celery_app.tasks["sweep_email_tokens"].ignore_result is True
    assert celery_app.conf.timezone == "UTC"
