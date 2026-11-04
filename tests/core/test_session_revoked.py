import time
import uuid
from datetime import datetime, timedelta, timezone

import fakeredis.aioredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

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


class DownRedis:
    """Redis unreachable: every read and write raises a RedisError subclass,
    and the writes it was asked for are recorded."""

    def __init__(self, error: type[RedisError] = RedisConnectionError):
        self.error = error
        self.writes: list[tuple] = []

    async def get(self, key):
        raise self.error("down")

    async def set(self, *args, **kwargs):
        self.writes.append(args)
        raise self.error("down")

    async def delete(self, *keys):
        self.writes.append(("delete", *keys))
        raise self.error("down")


class FetchSpy:
    def __init__(self, result):
        self.result = result
        self.calls: list[uuid.UUID] = []

    async def __call__(self, user_id):
        self.calls.append(user_id)
        return self.result


@pytest.mark.parametrize("error", [RedisError, RedisConnectionError, RedisTimeoutError])
async def test_redis_down_and_db_cutoff_after_login_is_revoked(error):
    cutoff = datetime.now(timezone.utc)
    fetch = FetchSpy(cutoff)
    c = claims(int(cutoff.timestamp()) - 3600)

    assert await session_revoked(DownRedis(error), c, fetch) is True
    assert fetch.calls == [c.sub]


async def test_redis_down_and_db_cutoff_before_login_is_not_revoked():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    fetch = FetchSpy(cutoff)
    c = claims(int(time.time()))

    assert await session_revoked(DownRedis(), c, fetch) is False
    assert fetch.calls == [c.sub]


async def test_redis_down_and_login_in_the_cutoffs_own_second_is_not_revoked():
    cutoff = datetime.fromtimestamp(1_700_000_000.85, tz=timezone.utc)
    fetch = FetchSpy(cutoff)

    assert await session_revoked(DownRedis(), claims(1_700_000_000), fetch) is False
    assert len(fetch.calls) == 1


async def test_redis_down_and_login_exactly_at_the_cutoff_is_not_revoked():
    cutoff = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
    fetch = FetchSpy(cutoff)

    assert await session_revoked(DownRedis(), claims(1_700_000_000), fetch) is False
    assert len(fetch.calls) == 1


async def test_redis_down_and_user_gone_is_revoked():
    fetch = FetchSpy(None)
    c = claims(int(time.time()))

    assert await session_revoked(DownRedis(), c, fetch) is True
    assert fetch.calls == [c.sub]


async def test_redis_down_and_db_unreachable_propagates_the_db_error():
    class DbDown(Exception):
        pass

    async def fetch(_uid):
        raise DbDown("db unreachable")

    with pytest.raises(DbDown):
        await session_revoked(DownRedis(), claims(int(time.time())), fetch)


@pytest.mark.parametrize(
    ("cutoff_offset_s", "expected"), [(+3600, True), (-3600, False)]
)
async def test_redis_down_the_verdict_comes_from_the_db_and_no_cache_write_is_attempted(
    cutoff_offset_s, expected
):
    # A write to a Redis whose read just failed is pointless.
    login = int(time.time()) - 60
    cutoff = datetime.fromtimestamp(login + cutoff_offset_s, tz=timezone.utc)
    redis = DownRedis()
    fetch = FetchSpy(cutoff)

    assert await session_revoked(redis, claims(login), fetch) is expected
    assert len(fetch.calls) == 1
    assert redis.writes == []


async def test_a_cached_cutoff_is_used_without_reading_the_db(redis):
    c = claims(int(time.time()))
    await publish_sva(redis, c.sub, datetime.now(timezone.utc) + timedelta(hours=1))

    async def fetch(_uid):
        raise AssertionError("a cache hit must not reach the DB")

    assert await session_revoked(redis, c, fetch) is True


async def test_a_cache_miss_reads_the_db_once_and_fills_the_cache(redis):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    fetch = FetchSpy(cutoff)
    c = claims(int(time.time()))

    assert await session_revoked(redis, c, fetch) is False
    assert fetch.calls == [c.sub]
    assert await redis.get(sva_cache_key(c.sub)) == str(int(cutoff.timestamp()))


async def test_publish_sva_returns_normally_when_redis_set_raises():
    redis = DownRedis()
    assert await publish_sva(redis, uuid.uuid4(), datetime.now(timezone.utc)) is None
    assert redis.writes, "publish_sva never attempted the cache write"


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


class FullRedis:
    """A Redis at maxmemory with noeviction: SET is refused with an OOM
    ResponseError, GET serves what is stored, DEL works."""

    def __init__(self, store: dict[str, str]):
        self.store = store

    async def get(self, key):
        return self.store.get(key)

    async def set(self, *args, **kwargs):
        raise ResponseError("OOM command not allowed when used memory > 'maxmemory'.")

    async def delete(self, *keys):
        return sum(self.store.pop(k, None) is not None for k in keys)


async def test_a_full_redis_refusing_the_publish_never_leaves_the_old_cutoff_in_force():
    now = datetime.now(timezone.utc)
    old_cutoff = now - timedelta(hours=1)
    new_cutoff = now - timedelta(seconds=1)
    c = claims(int((now - timedelta(minutes=30)).timestamp()))
    redis = FullRedis({sva_cache_key(c.sub): str(int(old_cutoff.timestamp()))})

    assert await publish_sva(redis, c.sub, new_cutoff) is None
    assert await session_revoked(redis, c, FetchSpy(new_cutoff)) is True


async def test_publish_sva_returns_normally_when_both_set_and_delete_raise():
    class DeadRedis(DownRedis):
        async def delete(self, *keys):
            self.writes.append(("delete", *keys))
            raise self.error("down")

    redis = DeadRedis()
    assert await publish_sva(redis, uuid.uuid4(), datetime.now(timezone.utc)) is None
    assert redis.writes, "publish_sva never attempted to write the cache"
