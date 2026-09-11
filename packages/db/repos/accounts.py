"""Linked OAuth identities. Not user-scoped: these functions run BEFORE the
caller has a session (mid-sign-in), so they take no user_id and rely on the
table being outside RLS (ADR 0012). Linking policy lives in the API
(apps/api/routers/internal_auth.py); this module only reads and inserts.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Account, User


async def get_user_by_account(
    session: AsyncSession, provider: str, provider_account_id: str
) -> User | None:
    result = await session.scalars(
        select(User)
        .join(Account, Account.user_id == User.id)
        .where(
            Account.provider == provider,
            Account.provider_account_id == provider_account_id,
        )
    )
    return result.first()


async def link(
    session: AsyncSession, user_id: uuid.UUID, provider: str, provider_account_id: str
) -> None:
    """The only place an accounts row is written; the route owns the commit."""
    session.add(
        Account(
            user_id=user_id, provider=provider, provider_account_id=provider_account_id
        )
    )
