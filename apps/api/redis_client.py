"""One shared async Redis client for the API process (rate limits + the
session-revocation cache). Lazy so importing never connects; uvicorn owns a
single event loop, so one client is loop-safe."""

import os

from redis.asyncio import Redis

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            # Bounded waits are what make the callers' `except RedisError` fail-open
            # branches reachable: a stalled (not dead) Redis answers nothing and
            # raises nothing, so an unbounded await would hang every authenticated
            # request on the revocation check. redis-py raises TimeoutError, a
            # RedisError subclass, so the existing handling applies unchanged.
            socket_timeout=2,
            socket_connect_timeout=1,
        )
    return _client
