"""Route-level fixtures: real Postgres (hax_test) + fakeredis + Bearer JWTs.

Two engines with deliberately different power:
- APP engine (packages.db.engine): connects as hax_app — what the routes under
  test use; RLS applies to it.
- ADMIN engine: connects as hax (owner; superuser in dev/CI) for seeding,
  truncation, and cross-user assertions that must see all rows.
Never seed through the app engine: RLS rejects un-announced writes.
"""

import asyncio
import os
import time
from pathlib import Path

import fakeredis.aioredis
import httpx
import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import apps.api.redis_client as redis_client
from packages.db import engine
from packages.db.session import to_async_url
from packages.db.user_context import current_user_id
from tests.api.factories import make_user

ROOT = Path(__file__).resolve().parents[2]
# tests/conftest.py hard-sets this to the hax_test owner connection — derive
# from it instead of a second literal DSN.
ADMIN_URL = os.environ["MIGRATIONS_DATABASE_URL"]
TEST_DB = "hax_test"

# Mirrors infra/docker-compose/postgres/init.sql so CI (bare service container)
# and a fresh clone need no manual role setup.
_APP_ROLE_SQL = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hax_app') THEN
    CREATE ROLE hax_app LOGIN PASSWORD 'hax_app'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;
"""
_GRANTS_SQL = (
    "GRANT USAGE ON SCHEMA public TO hax_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hax_app",
)


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Create hax_test + the app role if missing, migrate to head, grant."""
    import asyncpg

    async def prepare() -> None:
        # CREATE DATABASE can't run inside the target DB — connect to the
        # cluster's always-present maintenance DB instead.
        maintenance_dsn = ADMIN_URL.replace(f"/{TEST_DB}", "/postgres")
        conn = await asyncpg.connect(dsn=maintenance_dsn)
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB
            )
            if not exists:
                await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
            await conn.execute(_APP_ROLE_SQL)
        finally:
            await conn.close()

    asyncio.run(prepare())

    from alembic import command
    from alembic.config import Config

    # env.py routes this to MIGRATIONS_DATABASE_URL (tests/conftest.py) — the
    # owner migrates hax_test exactly as dev/prod are migrated.
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")

    async def grant() -> None:
        # Grants are per-database; init.sql only covered `hax`.
        conn = await asyncpg.connect(dsn=ADMIN_URL)
        try:
            for stmt in _GRANTS_SQL:
                await conn.execute(stmt)
        finally:
            await conn.close()

    asyncio.run(grant())


@pytest.fixture(scope="session")
def admin_engine():
    eng = create_async_engine(
        to_async_url(ADMIN_URL),
        poolclass=NullPool,  # session-scoped: must not pool loop-bound conns
    )
    yield eng
    asyncio.run(eng.dispose())


@pytest.fixture(autouse=True)
async def clean_db(admin_engine, test_database):
    async with admin_engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables"
                " WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
        tables = ", ".join(row[0] for row in rows)
        # f-string, not bound params: identifiers can't be bound, and the names
        # come from pg_tables, not from any user input. alembic_version is
        # excluded or the next run would re-apply every migration.
        if tables:
            await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    yield
    # pytest-asyncio gives each test its own event loop; the APP engine's
    # pooled asyncpg connections are loop-bound, so drop them or the next
    # test dies with "attached to a different loop".
    await engine.dispose()


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client, "_client", client)
    return client


@pytest.fixture(autouse=True)
def reset_identity():
    # ASGITransport runs the app inline, so a client-driven request sets
    # current_user_id inside the test's own task context; without a reset,
    # a later assert in the same test (or a differently-scoped session use)
    # could inherit an already-announced identity from a prior request.
    token = current_user_id.set(None)
    yield
    current_user_id.reset(token)


@pytest.fixture
async def client():
    from apps.api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def user_a(admin_engine):
    return await make_user(admin_engine, "a@test.local")


@pytest.fixture
async def user_b(admin_engine):
    return await make_user(admin_engine, "b@test.local")


def bearer(user) -> dict[str, str]:
    """Authorization header for `user` — the Bearer path, no cookie needed."""
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": str(user.id),
            "email": user.email,
            "iss": "hax",
            "aud": "hax-api",
            "iat": now,
            "exp": now + 600,
            "jti": "test",
            "auth_time": now,
        },
        os.environ["AUTH_SECRET"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}
