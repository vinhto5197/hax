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
            # Bounded waits make the callers' `except RedisError` reachable
            # (limiters fail open; revocation falls back to the DB): a stalled
            # Redis raises nothing, so an unbounded await would hang every
            # authenticated request. redis-py's TimeoutError is a RedisError.
            socket_timeout=2,
            socket_connect_timeout=1,
        )
    return _client
