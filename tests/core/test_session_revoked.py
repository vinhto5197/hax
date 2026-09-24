import time
import uuid
from datetime import datetime, timedelta, timezone

import fakeredis.aioredis
import pytest
from redis.exceptions import RedisError

from packages.core.auth.revocation import (
    SVA_CACHE_TTL_S,
    publish_sva,
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
    # -1 (no expiry) must fail: the TTL is what retires a deleted or externally
    # revoked account's cached cutoff.
    assert 0 < await redis.ttl(sva_cache_key(c.sub)) <= SVA_CACHE_TTL_S


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


async def test_a_cutoff_written_without_an_expiry_reads_as_ttl_minus_one(redis):
    # Redis returns -1 for a key that exists with no expiry (and -2 for a
    # missing key) — the value the cache-TTL assertion above must reject.
    assert await redis.ttl(sva_cache_key(uuid.uuid4())) == -2
    key = sva_cache_key(uuid.uuid4())
    await redis.set(key, "0")
    assert await redis.ttl(key) == -1


async def test_a_cache_fill_never_reinstates_an_older_cutoff(redis):
    # Interleaving: the miss path reads the old cutoff from the DB, then a
    # password reset bumps and publishes a newer one before the fill lands.
    # The fill must not overwrite it — the reset's revocation must hold.
    now = datetime.now(timezone.utc)
    old_cutoff = now - timedelta(hours=1)
    new_cutoff = now - timedelta(seconds=1)
    c = claims(int((now - timedelta(minutes=30)).timestamp()))

    async def fetch_then_reset(uid):
        await publish_sva(redis, uid, new_cutoff)  # the reset wins the race
        return old_cutoff

    await session_revoked(redis, c, fetch_then_reset)
    assert await redis.get(sva_cache_key(c.sub)) == str(int(new_cutoff.timestamp()))
    # And a later check for that session sees the reset, not the stale fill.
    assert await session_revoked(redis, c, fetch_then_reset) is True
