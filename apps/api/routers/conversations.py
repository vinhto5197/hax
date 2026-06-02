from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.deps import get_session
from packages.core.schemas.conversation import ConversationDetailOut, ConversationOut
from packages.db.models import Conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    session: AsyncSession = Depends(get_session),
) -> list[ConversationOut]:
    # Most-recently-active first — matches sidebar ordering. No auth filter
    # yet, so this returns every conversation.
    result = await session.scalars(
        select(Conversation).order_by(Conversation.updated_at.desc())
    )
    return [ConversationOut.model_validate(c) for c in result]


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ConversationDetailOut:
    # selectinload eager-loads messages in a second query (the relationship is
    # ordered by created_at), avoiding a lazy load in async context.
    result = await session.scalars(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    conversation = result.first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationDetailOut.model_validate(conversation)
