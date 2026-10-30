"""Prepare an isolated local stack's database and Redis db.

Two targets, each a throwaway of its own: `e2e` (the default; database
hax_e2e, Redis db 15) for the browser journeys (`make e2e`), and `explorer`
(hax_explorer, Redis db 14) for the weekly product explorer
(`scripts/explorer.sh`). Run from the repo root before the stack starts.
Idempotent: creates the database if missing, migrates it as the owner role,
grants the app role, empties every table but the migration ledger, seeds one
verified member, flushes the Redis db. The `e2e` target also requires the
dev S3 stand-in (its uploads land in the stand-in's hax-e2e bucket) and never
empties it: object keys are unique per document and the database is
truncated, so a leftover object is never referenced. It also requires the
journeys' own Mailpit (mailpit-e2e, :8026) and empties it; dev's inbox is a
separate container.
The connection targets are literals, never env: the dev shell exports the
root .env (direnv), and this script must be unable to reach dev data.
"""

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ADMIN_URL = "postgresql://hax:hax@localhost:5432/postgres"
S3_HEALTH_URL = "http://localhost:9000/health"
MAILPIT_URL = "http://localhost:8026"


@dataclass(frozen=True)
class Target:
    database: str
    redis_db: int
    # The member each stack logs in as; e2e's is a contract with
    # e2e/auth.setup.ts, the explorer's with scripts/explorer.sh.
    member_email: str
    member_name: str
    member_password: str
    # Only the journeys' stack uploads (playwright.config.ts points it here).
    needs_storage: bool = False
    # Only the journeys' stack sends to Mailpit (playwright.config.ts).
    needs_mail: bool = False

    @property
    def owner_url(self) -> str:
        return f"postgresql://hax:hax@localhost:5432/{self.database}"

    @property
    def app_url(self) -> str:
        return f"postgresql://hax_app:hax_app@localhost:5432/{self.database}"

    @property
    def redis_url(self) -> str:
        return f"redis://localhost:6379/{self.redis_db}"


# Every entry is emptied on each run: never `hax` (dev), `hax_test` (pytest)
# or Redis db 0 (dev), and no two entries share a database or a Redis db.
TARGETS = {
    "e2e": Target(
        "hax_e2e",
        15,
        "e2e@example.com",
        "E2E",
        "e2e-password-123",
        needs_storage=True,
        needs_mail=True,
    ),
    "explorer": Target(
        "hax_explorer", 14, "explorer@example.com", "Explorer", "explorer-password-123"
    ),
}

ROOT = Path(__file__).resolve().parents[3]


def parse_target(argv: list[str]) -> Target:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=sorted(TARGETS), default="e2e")
    return TARGETS[parser.parse_args(argv).target]


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


async def create_database(target: Target) -> None:
    import asyncpg

    try:
        conn = await asyncpg.connect(dsn=ADMIN_URL, timeout=5)
    except OSError as exc:
        fail(f"Postgres unreachable ({type(exc).__name__}): run make infra-up")
    except asyncpg.PostgresError as exc:
        fail(f"cannot log in to Postgres as hax ({type(exc).__name__})")
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", target.database
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{target.database}"')
        await conn.execute(_APP_ROLE_SQL)
    finally:
        await conn.close()
    print(f"database {target.database}: {'present' if exists else 'created'}")


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    print("migrations: at head")


async def grant_reset_seed(target: Target) -> None:
    import asyncpg

    from packages.core.auth.passwords import hash_password

    conn = await asyncpg.connect(dsn=target.owner_url, timeout=5)
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
            target.member_email,
            target.member_name,
            hash_password(target.member_password),
            now,
        )
        print(f"seeded: {target.member_email}")
    finally:
        await conn.close()


def flush_redis(target: Target) -> None:
    import redis

    try:
        redis.Redis.from_url(target.redis_url, socket_connect_timeout=5).flushdb()
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as exc:
        fail(f"Redis unreachable ({type(exc).__name__}): run make infra-up")
    print(f"redis db {target.redis_db}: flushed")


def check_storage() -> None:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(S3_HEALTH_URL, timeout=5) as response:
            ready = response.status == 200
    except (urllib.error.URLError, OSError):
        ready = False
    if not ready:
        fail("S3 stand-in unreachable: run make infra-up")
    print("s3 stand-in: ready")


def check_and_clear_mail() -> None:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{MAILPIT_URL}/livez", timeout=5) as response:
            ready = response.status == 200
    except (urllib.error.URLError, OSError):
        ready = False
    if not ready:
        fail("Mailpit unreachable: run make infra-up")

    request = urllib.request.Request(f"{MAILPIT_URL}/api/v1/messages", method="DELETE")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, OSError) as exc:
        fail(f"Mailpit cleanup failed ({type(exc).__name__}): run make infra-up")
    if status != 200:
        fail(f"Mailpit cleanup failed ({status}): run make infra-up")
    print("mailpit-e2e: emptied")


def main(argv: list[str]) -> None:
    target = parse_target(argv)
    if target.needs_storage:
        check_storage()
    if target.needs_mail:
        check_and_clear_mail()
    assert target.owner_url.endswith(f"/{target.database}")
    # Alembic's env.py and packages.db read these at import; set before either
    # is imported so nothing from the shell can redirect the migration.
    os.environ["MIGRATIONS_DATABASE_URL"] = target.owner_url
    os.environ["DATABASE_URL"] = target.app_url
    sys.path.insert(0, str(ROOT))
    asyncio.run(create_database(target))
    migrate()
    asyncio.run(grant_reset_seed(target))
    flush_redis(target)


if __name__ == "__main__":
    main(sys.argv[1:])
