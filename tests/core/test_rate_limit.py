import fakeredis.aioredis
import pytest
from redis.exceptions import RedisError

from packages.core.auth.rate_limit import hit


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_allows_up_to_limit(redis):
    results = [await hit(redis, "t", "k", limit=3, window_s=60) for _ in range(3)]
    assert results == [True, True, True]


async def test_blocks_over_limit(redis):
    for _ in range(3):
        await hit(redis, "t", "k", limit=3, window_s=60)
    assert await hit(redis, "t", "k", limit=3, window_s=60) is False


async def test_idents_are_independent(redis):
    for _ in range(3):
        await hit(redis, "t", "a", limit=3, window_s=60)
    assert await hit(redis, "t", "b", limit=3, window_s=60) is True


async def test_key_expires(redis):
    await hit(redis, "t", "k", limit=1, window_s=60)
    assert await redis.ttl("rl:t:k") > 0


async def test_fails_open_on_redis_error(caplog):
    class BrokenRedis:
        async def incr(self, key):
            raise RedisError("down")

    assert await hit(BrokenRedis(), "t", "k", limit=1, window_s=60) is True
    assert "rate limiter unavailable" in caplog.text
