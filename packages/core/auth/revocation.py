"""Session revocation: auth_time vs users.sessions_valid_after.

Redis is a write-through cache over the DB column — anything that bumps the
cutoff (password reset) MUST write both, via publish_sva, so
revocation is instant for cached users. Missing user => revoked on the next
cache miss (a deleted account's tokens die within SVA_CACHE_TTL_S unless the
deleter purges the key). A Redis error on the read falls back to the DB
cutoff, the source of truth, so a revoked session stays revoked while Redis
is down (one indexed read per request meanwhile). DB fetch errors propagate
— an unreachable DB is a real outage.
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
    # to it, so a Redis failure degrades to "revoked within TTL": the DB is the
    # source of truth, and a cache write is never a reason to fail the request.
    try:
        await redis.set(
            sva_cache_key(user_id), _encode_cutoff(cutoff), ex=SVA_CACHE_TTL_S
        )
    except RedisError:
        logger.warning(
            "sva cache publish failed; dropping the cached cutoff", exc_info=True
        )
        # A full Redis (noeviction) refuses the SET but still serves the old
        # cutoff on GET; DEL is allowed there, so the next check misses and
        # reads the DB. Dead Redis fails this too, and the read path's own
        # fallback covers that.
        try:
            await redis.delete(sva_cache_key(user_id))
        except RedisError:
            logger.warning(
                "sva cache delete failed too; DB cutoff stands", exc_info=True
            )


async def session_revoked(
    redis,
    claims: SessionClaims,
    fetch_sva: Callable[[uuid.UUID], Awaitable[datetime | None]],
) -> bool:
    key = sva_cache_key(claims.sub)
    try:
        cached = await redis.get(key)
    except RedisError:
        logger.warning("sva cache unavailable; reading the DB cutoff", exc_info=True)
        cutoff = await fetch_sva(claims.sub)
        return cutoff is None or claims.auth_time < int(_encode_cutoff(cutoff))
    if cached is None:
        cutoff = await fetch_sva(claims.sub)
        if cutoff is None:
            return True
        # Fill only if still absent: a bump that landed between the DB read
        # and this write is newer than what was read, and cutoffs only move
        # forward — so an unconditional SET could reinstate a revoked window.
        try:
            await redis.set(key, _encode_cutoff(cutoff), ex=SVA_CACHE_TTL_S, nx=True)
        except RedisError:
            logger.warning("sva cache fill failed; DB cutoff stands", exc_info=True)
        cached = _encode_cutoff(cutoff)
    return claims.auth_time < int(cached)
