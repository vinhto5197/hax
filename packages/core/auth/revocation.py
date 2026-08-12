"""Session revocation: auth_time vs users.sessions_valid_after.

Redis is a write-through cache over the DB column — anything that bumps the
cutoff (password reset, slice 4) MUST write both, keyed by sva_cache_key, so
revocation is instant for cached users. Missing user => revoked (a deleted
account's tokens die immediately). RedisError => fail open (core auth still
enforced); DB fetch errors propagate — an unreachable DB is a real outage.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from redis.exceptions import RedisError

from packages.core.auth.tokens import SessionClaims

logger = logging.getLogger(__name__)

SVA_CACHE_TTL_S = 300


def sva_cache_key(user_id: uuid.UUID) -> str:
    return f"sva:{user_id}"


async def session_revoked(
    redis,
    claims: SessionClaims,
    fetch_sva: Callable[[uuid.UUID], Awaitable[datetime | None]],
) -> bool:
    key = sva_cache_key(claims.sub)
    try:
        cached = await redis.get(key)
    except RedisError:
        logger.warning("sva cache unavailable; failing open", exc_info=True)
        return False
    if cached is None:
        cutoff = await fetch_sva(claims.sub)
        if cutoff is None:
            return True
        cached = str(int(cutoff.timestamp()))
        try:
            await redis.set(key, cached, ex=SVA_CACHE_TTL_S)
        except RedisError:
            logger.warning("sva cache write failed; continuing", exc_info=True)
    return claims.auth_time < int(cached)
