"""User queries — the first repo module (M2.5 slice 1).

Repo-layer contract (spec: Isolation): this is the only place the app reads or
writes user rows; emails are normalized to lowercase HERE so every caller gets
case-insensitive semantics without remembering to. Slice 2 extends the repo
pattern to conversations/documents.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import User


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.scalars(
        select(User).where(func.lower(User.email) == email.strip().lower())
    )
    return result.first()


async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def create_password_user(
    session: AsyncSession, email: str, password_hash: str, name: str | None
) -> User:
    user = User(email=email.strip().lower(), password_hash=password_hash, name=name)
    session.add(user)
    # flush not commit: the route owns the transaction boundary.
    await session.flush()
    return user


async def get_sessions_valid_after(
    session: AsyncSession, user_id: uuid.UUID
) -> datetime | None:
    result = await session.execute(
        select(User.sessions_valid_after).where(User.id == user_id)
    )
    row = result.first()
    return row[0] if row else None
