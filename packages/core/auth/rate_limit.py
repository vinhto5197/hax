"""Fixed-window rate limiting on Redis.

Fail-open contract (spec threat table): Redis being down degrades limiting
(allow + loud log), never availability. Callers pick names/limits; keys are
rl:{name}:{ident}.
"""

import logging

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


async def hit(redis, name: str, ident: str, limit: int, window_s: int) -> bool:
    """Record one hit; True = allowed, False = over the window's limit."""
    key = f"rl:{name}:{ident}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_s)
        elif await redis.ttl(key) == -1:
            # Heal a missing TTL (crash between INCR and EXPIRE) so the key
            # can't silently become a permanent lockout.
            await redis.expire(key, window_s)
        return count <= limit
    except RedisError:
        logger.warning(
            "rate limiter unavailable; failing open for %s", name, exc_info=True
        )
        return True
