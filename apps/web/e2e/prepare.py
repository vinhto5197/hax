"""Prepare the isolated browser-journey stack: database hax_e2e and Redis db 15.

Run from the repo root before Playwright (`make e2e`). Idempotent: creates the
database if missing, migrates it as the owner role, grants the app role,
empties every table but the migration ledger, seeds one verified member,
flushes Redis db 15.
The connection targets are literals, never env: the dev shell exports the
root .env (direnv), and this script must be unable to reach dev data.
"""

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

TARGET_DB = "hax_e2e"
ADMIN_URL = "postgresql://hax:hax@localhost:5432/postgres"
OWNER_URL = f"postgresql://hax:hax@localhost:5432/{TARGET_DB}"
APP_URL = f"postgresql://hax_app:hax_app@localhost:5432/{TARGET_DB}"
REDIS_URL = "redis://localhost:6379/15"

# Contract with e2e/auth.setup.ts, which logs in with these.
MEMBER_EMAIL = "e2e@example.com"
MEMBER_NAME = "E2E"
MEMBER_PASSWORD = "e2e-password-123"

ROOT = Path(__file__).resolve().parents[3]

assert TARGET_DB == "hax_e2e" and OWNER_URL.endswith("/hax_e2e")

# Alembic's env.py and packages.db read these at import; set before either is
# imported so nothing from the shell can redirect the migration.
os.environ["MIGRATIONS_DATABASE_URL"] = OWNER_URL
os.environ["DATABASE_URL"] = APP_URL
sys.path.insert(0, str(ROOT))

# Mirrors tests/api/conftest.py (_APP_ROLE_SQL, _GRANTS_SQL); grants are
# per-database, and init.sql only covered `hax`.
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
    "REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM hax_app",
)


def fail(message: str) -> None:
    print(f"e2e prepare: {message}", file=sys.stderr)
    sys.exit(1)


async def create_database() -> None:
    import asyncpg

    try:
        conn = await asyncpg.connect(dsn=ADMIN_URL, timeout=5)
    except OSError as exc:
        fail(f"Postgres unreachable ({type(exc).__name__}): run make infra-up")
    except asyncpg.PostgresError as exc:
        fail(f"cannot log in to Postgres as hax ({type(exc).__name__})")
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TARGET_DB
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TARGET_DB}"')
        await conn.execute(_APP_ROLE_SQL)
    finally:
        await conn.close()
    print(f"database {TARGET_DB}: {'present' if exists else 'created'}")


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    print("migrations: at head")


async def grant_reset_seed() -> None:
    import asyncpg

    from packages.core.auth.passwords import hash_password

    conn = await asyncpg.connect(dsn=OWNER_URL, timeout=5)
    try:
        for stmt in _GRANTS_SQL:
            await conn.execute(stmt)
        print("grants: hax_app")

        # Every table except the migration ledger: whatever a journey wrote,
        # including tables with no foreign key to users, is gone.
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables"
            " WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
        )
        names = ", ".join(f'"{row["tablename"]}"' for row in tables)
        await conn.execute(f"TRUNCATE {names} CASCADE")
        print(f"truncated: {len(tables)} tables")

        # sessions_valid_after from the app clock, as the ORM stamps it (see
        # tests/api/factories.py): the DB clock runs ahead, and a token minted
        # in the same second would otherwise read as revoked.
        now = datetime.now(UTC)
        await conn.execute(
            "INSERT INTO users"
            " (email, name, password_hash, email_verified_at, sessions_valid_after)"
            " VALUES ($1, $2, $3, $4, $4)",
            MEMBER_EMAIL,
            MEMBER_NAME,
            hash_password(MEMBER_PASSWORD),
            now,
        )
        print(f"seeded: {MEMBER_EMAIL}")
    finally:
        await conn.close()


def flush_redis() -> None:
    import redis

    assert REDIS_URL.endswith("/15")
    try:
        redis.Redis.from_url(REDIS_URL, socket_connect_timeout=5).flushdb()
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as exc:
        fail(f"Redis unreachable ({type(exc).__name__}): run make infra-up")
    print("redis db 15: flushed")


def main() -> None:
    asyncio.run(create_database())
    migrate()
    asyncio.run(grant_reset_seed())
    flush_redis()


if __name__ == "__main__":
    main()
