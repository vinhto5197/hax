"""Session revocation: auth_time vs users.sessions_valid_after.

Redis is a write-through cache over the DB column — anything that bumps the
cutoff (password reset) MUST write both, via publish_sva, so
revocation is instant for cached users. Missing user => revoked on the next
cache miss (a deleted account's tokens die within SVA_CACHE_TTL_S unless the
deleter purges the key). RedisError => fail open (core auth still
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


def _encode_cutoff(cutoff: datetime) -> str:
    return str(int(cutoff.timestamp()))


async def publish_sva(redis, user_id: uuid.UUID, cutoff: datetime) -> None:
    # The DB write is already committed by the caller; a cache miss falls back
    # to it, so a Redis failure degrades to "revoked within TTL" — consistent
    # with the fail-open policy above, not a reason to fail the request.
    try:
        await redis.set(
            sva_cache_key(user_id), _encode_cutoff(cutoff), ex=SVA_CACHE_TTL_S
        )
    except RedisError:
        logger.warning("sva cache publish failed; DB cutoff stands", exc_info=True)


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
        await publish_sva(redis, claims.sub, cutoff)
        cached = _encode_cutoff(cutoff)
    return claims.auth_time < int(cached)
