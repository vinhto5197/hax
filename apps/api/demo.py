"""The anonymous demo's limits (a visitor is a user whose token has no email).

The demo opens model spend to anyone, so a visitor gets DEMO_TURN_LIMIT user
turns in total, checked before anything is persisted, and no uploads at all
(the guest chat has no document search to use them with). 403
{"code": "demo_limit"} is the one signal the web client turns into the
sign-up prompt.
"""

import os

from fastapi import HTTPException

from apps.api.auth import CurrentUser
from packages.db import AsyncSessionLocal
from packages.db.repos import conversations as conversations_repo


def _turn_limit() -> int:
    return int(os.getenv("DEMO_TURN_LIMIT", "3"))


def _refuse() -> HTTPException:
    return HTTPException(403, detail={"code": "demo_limit"})


def is_visitor(user: CurrentUser) -> bool:
    return user.email is None


async def enforce_turn_cap(user: CurrentUser) -> None:
    if not is_visitor(user):
        return
    # Own short session: the chat route holds no request-scoped one.
    async with AsyncSessionLocal() as session:
        turns = await conversations_repo.count_user_messages(session, user.id)
    if turns >= _turn_limit():
        raise _refuse()


def refuse_visitor(user: CurrentUser) -> None:
    if is_visitor(user):
        raise _refuse()
