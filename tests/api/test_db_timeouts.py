"""The app's database connections bound how long a statement may wait for a
lock and how long it may run (backlog 82): a hang behind someone else's lock
fails in seconds instead of holding a request for minutes. Exercised through
packages.db.engine on real connections, as the app uses them.
"""

import asyncio
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from packages.db import engine
from packages.db.session import MIGRATIONS_DATABASE_URL_ASYNC


async def _show(name: str) -> str:
    async with engine.connect() as conn:
        return (await conn.execute(text(f"SHOW {name}"))).scalar_one()


async def test_an_app_connection_waits_at_most_five_seconds_for_a_lock():
    assert await _show("lock_timeout") == "5s"


async def test_an_app_statement_runs_at_most_thirty_seconds():
    assert await _show("statement_timeout") == "30s"


async def test_a_statement_blocked_by_another_sessions_lock_fails_instead_of_hanging():
    # The owner role holds an exclusive lock on a scratch table in an open
    # transaction; an app connection asking for the same lock gives up at its
    # lock_timeout with an error, rather than waiting for the holder.
    holder = create_async_engine(MIGRATIONS_DATABASE_URL_ASYNC)
    try:
        async with holder.connect() as setup:
            await setup.execute(text("CREATE TABLE IF NOT EXISTS lock_probe (id int)"))
            await setup.execute(text("GRANT ALL ON lock_probe TO PUBLIC"))
            await setup.commit()
        async with holder.connect() as hold:
            await hold.execute(text("LOCK TABLE lock_probe IN ACCESS EXCLUSIVE MODE"))
            started = time.monotonic()
            # wait_for: without the limit this would wait forever, so a
            # regression fails the test instead of hanging the suite.
            with pytest.raises(DBAPIError, match="lock timeout"):
                async with engine.connect() as conn:
                    await asyncio.wait_for(
                        conn.execute(text("SELECT * FROM lock_probe")), 20
                    )
            assert 4 < time.monotonic() - started < 15
            await hold.rollback()
        async with holder.connect() as cleanup:
            await cleanup.execute(text("DROP TABLE IF EXISTS lock_probe"))
            await cleanup.commit()
    finally:
        await holder.dispose()


async def test_migrations_keep_their_own_connection_without_the_app_limits():
    # A migration may legitimately wait on locks or run long; the limits are
    # the app's, set on the app engine only.
    owner = create_async_engine(MIGRATIONS_DATABASE_URL_ASYNC)
    try:
        async with owner.connect() as conn:
            assert (await conn.execute(text("SHOW lock_timeout"))).scalar_one() == "0"
    finally:
        await owner.dispose()
