import time
import uuid
from datetime import datetime, timedelta, timezone

import fakeredis.aioredis
import pytest
from redis.exceptions import RedisError

from packages.core.auth.revocation import (
    SVA_CACHE_TTL_S,
    session_revoked,
    sva_cache_key,
)
from packages.core.auth.tokens import SessionClaims


def claims(auth_time: int) -> SessionClaims:
    return SessionClaims(
        sub=uuid.uuid4(), email="a@example.com", auth_time=auth_time, jti="j"
    )


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_fresh_login_not_revoked(redis):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    async def fetch(_uid):
        return cutoff

    assert await session_revoked(redis, claims(int(time.time())), fetch) is False


async def test_login_before_cutoff_revoked(redis):
    cutoff = datetime.now(timezone.utc)

    async def fetch(_uid):
        return cutoff

    old = int(cutoff.timestamp()) - 3600
    assert await session_revoked(redis, claims(old), fetch) is True


async def test_unknown_user_revoked(redis):
    async def fetch(_uid):
        return None

    assert await session_revoked(redis, claims(int(time.time())), fetch) is True


async def test_cutoff_cached_after_first_check(redis):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    calls = 0

    async def fetch(_uid):
        nonlocal calls
        calls += 1
        return cutoff

    c = claims(int(time.time()))
    await session_revoked(redis, c, fetch)
    await session_revoked(redis, c, fetch)
    assert calls == 1
    assert await redis.ttl(sva_cache_key(c.sub)) <= SVA_CACHE_TTL_S


async def test_same_second_mint_not_revoked(redis):
    # sessions_valid_after lands mid-second (e.g. .85); a token minted in the
    # same wall-clock second has auth_time floored to the second's start.
    # The int() floor on the cutoff must make these compare as NOT revoked.
    cutoff = datetime.fromtimestamp(1_700_000_000.85, tz=timezone.utc)

    async def fetch(_uid):
        return cutoff

    assert await session_revoked(redis, claims(1_700_000_000), fetch) is False


async def test_fails_open_on_redis_error():
    class BrokenRedis:
        async def get(self, key):
            raise RedisError("down")

    async def fetch(_uid):
        raise AssertionError("must not reach the DB when failing open")

    assert await session_revoked(BrokenRedis(), claims(0), fetch) is False
