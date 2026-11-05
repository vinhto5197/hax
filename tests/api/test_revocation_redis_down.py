"""Session revocation with Redis down: the cutoff comes from Postgres, so a
session minted before a password reset dies even while the cache is
unreachable, and a fresh session still works."""

import time

import fakeredis
import fakeredis.aioredis
import pytest
from sqlalchemy import text

import apps.api.redis_client as redis_client
from packages.core.auth.email_tokens import hash_token
from tests.api.conftest import bearer
from tests.api.factories import make_email_token, make_user


@pytest.fixture
def redis_down(monkeypatch):
    """The API's Redis client raises ConnectionError (a RedisError) on every
    command, pipelines and scripts included."""
    server = fakeredis.FakeServer()
    server.connected = False
    client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    monkeypatch.setattr(redis_client, "_client", client)
    return client


async def test_redis_down_a_session_minted_before_the_cutoff_is_401(
    client, admin_engine, redis_down
):
    u = await make_user(admin_engine, "r@example.com")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET sessions_valid_after = now() WHERE id = :id"),
            {"id": u.id},
        )
    old = bearer(u, auth_time=int(time.time()) - 3600)

    res = await client.get("/api/conversations", headers=old)
    assert res.status_code == 401


async def test_redis_down_a_password_reset_kills_the_sessions_minted_before_it(
    client, admin_engine, redis_down
):
    u = await make_user(admin_engine, "r@example.com")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE users SET sessions_valid_after = now() - interval '1 day'"
                " WHERE id = :id"
            ),
            {"id": u.id},
        )
    old = bearer(u, auth_time=int(time.time()) - 120)
    await make_email_token(admin_engine, u.id, "reset_password", hash_token("raw1"))

    reset = await client.post(
        "/api/auth/reset-password", json={"token": "raw1", "password": "brand-new-9"}
    )
    assert reset.status_code == 200

    res = await client.get("/api/conversations", headers=old)
    assert res.status_code == 401


async def test_redis_down_a_fresh_session_is_200(client, user_a, redis_down):
    res = await client.get("/api/conversations", headers=bearer(user_a))
    assert res.status_code == 200
