"""The batch deletes behind the daily sweeps honor `limit` whatever plan the
planner picks: one call never removes more than `limit` rows, and a full batch
is exactly `limit` while candidates remain.

The planner is pushed toward a nested loop that rescans the limited
`FOR UPDATE SKIP LOCKED` subquery; a rescan that skips the rows this same
statement already deleted would pick fresh ones and over-delete. Two levers:
the table is ANALYZEd while it holds one candidate, so the outer scan is
estimated at one row and a per-row rescan looks free; and the join and
aggregate strategies that would evaluate the subquery once are SET LOCAL off
inside the transaction that runs the delete, through the app engine the sweep
tasks use. Each call starts on a fresh connection: asyncpg caches a prepared
statement per connection, and the generic plan it can settle on would
ignore the settings. Seeds and the after-commit counts go through admin_engine (another
connection)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from packages.core.auth.email_tokens import hash_token
from packages.db import AsyncSessionLocal
from packages.db import engine as app_engine
from packages.db.repos import email_tokens
from packages.db.repos import users as users_repo
from tests.api.factories import make_email_token, make_user, make_visitor

CANDIDATES = 20
LIMIT = 2
EXPIRED = -60  # seconds: a negative TTL seeds a row that expired a minute ago

# Planner knobs that steer `id IN (SELECT ... LIMIT n FOR UPDATE SKIP LOCKED)`
# into a nested loop whose inner side is the subquery, re-executed per outer row.
RESCAN_PLAN_SETTINGS = (
    "SET LOCAL enable_hashjoin = off",
    "SET LOCAL enable_mergejoin = off",
    "SET LOCAL enable_material = off",
    "SET LOCAL enable_hashagg = off",
    "SET LOCAL enable_sort = off",
)


@pytest.fixture(autouse=True)
async def fresh_planner_stats(admin_engine):
    """The skewed statistics this file plants must not outlive it."""
    yield
    async with admin_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("ANALYZE users"))
        await conn.execute(text("ANALYZE email_tokens"))


async def _analyze(admin_engine, table: str) -> None:
    async with admin_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text(f"ANALYZE {table}"))


async def _push_toward_rescan(session) -> None:
    for stmt in RESCAN_PLAN_SETTINGS:
        await session.execute(text(stmt))


async def _seed_aged_visitors(admin_engine, n: int) -> None:
    await _seed_aged_visitor_rows(admin_engine, 1)
    await _analyze(admin_engine, "users")
    await _seed_aged_visitor_rows(admin_engine, n - 1)


async def _seed_aged_visitor_rows(admin_engine, n: int) -> None:
    for _ in range(n):
        visitor = await make_visitor(admin_engine)
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE users SET created_at = now() - make_interval(days => 4)"
                    " WHERE id = :id"
                ),
                {"id": visitor.id},
            )


async def _seed_dead_tokens(admin_engine, n: int) -> None:
    u = await make_user(admin_engine, "dead-tokens@test.local")
    await _seed_dead_token_rows(admin_engine, u.id, range(1))
    await _analyze(admin_engine, "email_tokens")
    await _seed_dead_token_rows(admin_engine, u.id, range(1, n))


async def _seed_dead_token_rows(admin_engine, user_id, indices) -> None:
    for i in indices:
        await make_email_token(
            admin_engine,
            user_id,
            "verify_email",
            hash_token(f"dead-{i}"),
            expires_in_s=EXPIRED if i % 2 else 3600,
            used=not i % 2,
        )


async def _visitors_left(admin_engine) -> int:
    async with admin_engine.connect() as conn:
        row = await conn.execute(text("SELECT count(*) FROM users WHERE email IS NULL"))
        return row.scalar_one()


async def _tokens_left(admin_engine) -> int:
    async with admin_engine.connect() as conn:
        row = await conn.execute(text("SELECT count(*) FROM email_tokens"))
        return row.scalar_one()


def _cutoff() -> datetime:
    return datetime.now(UTC) - timedelta(days=3)


async def _delete_visitors_once(limit: int) -> list:
    await app_engine.dispose()
    async with AsyncSessionLocal() as session:
        await _push_toward_rescan(session)
        ids = await users_repo.delete_stale_anonymous(session, _cutoff(), limit)
        await session.commit()
    return ids


async def _delete_tokens_once(limit: int) -> int:
    await app_engine.dispose()
    async with AsyncSessionLocal() as session:
        await _push_toward_rescan(session)
        deleted = await email_tokens.delete_dead(session, limit=limit)
        await session.commit()
    return deleted


async def test_delete_stale_anonymous_never_exceeds_limit_on_a_rescanning_plan(
    admin_engine,
):
    await _seed_aged_visitors(admin_engine, CANDIDATES)
    assert await _visitors_left(admin_engine) == CANDIDATES

    ids = await _delete_visitors_once(LIMIT)

    gone = CANDIDATES - await _visitors_left(admin_engine)
    assert len(ids) <= LIMIT, f"returned {len(ids)} ids for limit {LIMIT}"
    assert gone <= LIMIT, f"{gone} visitors deleted for limit {LIMIT}"


async def test_delete_dead_never_exceeds_limit_on_a_rescanning_plan(
    admin_engine,
):
    await _seed_dead_tokens(admin_engine, CANDIDATES)
    assert await _tokens_left(admin_engine) == CANDIDATES

    deleted = await _delete_tokens_once(LIMIT)

    gone = CANDIDATES - await _tokens_left(admin_engine)
    assert deleted <= LIMIT, f"returned {deleted} for limit {LIMIT}"
    assert gone <= LIMIT, f"{gone} tokens deleted for limit {LIMIT}"


async def test_delete_stale_anonymous_takes_exactly_limit_until_a_short_batch(
    admin_engine,
):
    seeded = 5
    await _seed_aged_visitors(admin_engine, seeded)

    batches: list[int] = []
    gone_per_call: list[int] = []
    for _ in range(seeded + 1):
        before = await _visitors_left(admin_engine)
        ids = await _delete_visitors_once(LIMIT)
        batches.append(len(ids))
        gone_per_call.append(before - await _visitors_left(admin_engine))
        if len(ids) < LIMIT:
            break

    assert batches == [2, 2, 1]
    assert gone_per_call == [2, 2, 1]
    assert await _visitors_left(admin_engine) == 0


async def test_delete_dead_takes_exactly_limit_until_a_short_batch(
    admin_engine,
):
    seeded = 5
    await _seed_dead_tokens(admin_engine, seeded)

    batches: list[int] = []
    gone_per_call: list[int] = []
    for _ in range(seeded + 1):
        before = await _tokens_left(admin_engine)
        deleted = await _delete_tokens_once(LIMIT)
        batches.append(deleted)
        gone_per_call.append(before - await _tokens_left(admin_engine))
        if deleted < LIMIT:
            break

    assert batches == [2, 2, 1]
    assert gone_per_call == [2, 2, 1]
    assert await _tokens_left(admin_engine) == 0
