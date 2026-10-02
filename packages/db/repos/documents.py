"""Document queries, scoped by owner. Same contract as the conversations
repo: user_id required; ownership miss -> None -> route 404."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Document


async def list_for_user(
    session: AsyncSession, user_id: uuid.UUID
) -> Sequence[Document]:
    result = await session.scalars(
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(Document.created_at.desc())
    )
    return result.all()


async def get_owned(
    session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID
) -> Document | None:
    result = await session.scalars(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    )
    return result.first()


async def create(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    filename: str,
    mime_type: str,
    size_bytes: int,
) -> Document:
    doc = Document(
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        status="pending",
        user_id=user_id,
    )
    session.add(doc)
    # flush, not commit: fills the server-default id so the caller can key the
    # storage object; the caller owns the transaction boundary.
    await session.flush()
    return doc


async def delete_owned(
    session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID
) -> Document | None:
    """Delete and return the row — the caller reads storage_key after commit
    (expire_on_commit=False keeps attributes loaded). None on ownership miss.
    Chunks go via ON DELETE CASCADE (passive_deletes on the model)."""
    doc = await get_owned(session, user_id, document_id)
    if doc is None:
        return None
    await session.delete(doc)
    return doc


async def fail_stale(
    session: AsyncSession, user_id: uuid.UUID, cutoff: datetime, error: str
) -> int:
    """Record 'failed' on the caller's documents still pending or processing
    since before `cutoff`; returns how many. The pipeline cannot give itself
    this deadline: a worker killed mid-task leaves no one to write the
    terminal status. Scoped to one user, so it runs under RLS as the caller."""
    result = await session.execute(
        update(Document)
        .where(
            Document.user_id == user_id,
            Document.status.in_(("pending", "processing")),
            Document.updated_at < cutoff,
        )
        .values(status="failed", error=error)
        .returning(Document.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())
