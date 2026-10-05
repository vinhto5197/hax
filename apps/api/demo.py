"""The anonymous demo's limits (a visitor is a user whose token has no email).

The demo opens model spend to anyone, so a visitor gets DEMO_TURN_LIMIT user
turns in total and no uploads at all (the guest chat has no document search
to use them with). The turns are counted by a per-visitor counter that only
goes up, never by what is in the database, so deleting a conversation does
not refund them. 403 {"code": "demo_limit"} is the one signal
the web client turns into the sign-up prompt.
"""

import os

from fastapi import HTTPException

from apps.api.auth import CurrentUser
from apps.api.redis_client import get_redis
from packages.core.auth import rate_limit


def _turn_limit() -> int:
    return int(os.getenv("DEMO_TURN_LIMIT", "3"))


def _turn_window_s() -> int:
    # The counter must outlive the visitor's row: the sweep runs once a day
    # after the retention, so a key that expired at exactly the retention
    # would hand the same token a second batch of turns in the gap.
    return (int(os.getenv("ANON_RETENTION_DAYS", "3")) + 2) * 86400


def _refuse() -> HTTPException:
    return HTTPException(403, detail={"code": "demo_limit"})


def is_visitor(user: CurrentUser) -> bool:
    return user.email is None


async def enforce_turn_cap(user: CurrentUser) -> None:
    """Spend one of the visitor's turns, or refuse. One atomic INCR per call:
    concurrent sends cannot all read the same count. Called before the turn is
    persisted, so a refused turn leaves no trace; a turn the model then fails
    is still spent. Fails open with Redis, like every limiter here."""
    if not is_visitor(user):
        return
    allowed = await rate_limit.hit(
        get_redis(),
        "demo_turns",
        str(user.id),
        limit=_turn_limit(),
        window_s=_turn_window_s(),
    )
    if not allowed:
        raise _refuse()


def refuse_visitor(user: CurrentUser) -> None:
    if is_visitor(user):
        raise _refuse()
