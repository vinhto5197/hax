from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import CurrentUser, current_user
from apps.api.deps import get_session
from packages.core.schemas.conversation import ConversationDetailOut, ConversationOut
from packages.db.repos import conversations as conversations_repo

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> list[ConversationOut]:
    # Most-recently-active first — matches sidebar ordering.
    conversations = await conversations_repo.list_for_user(session, user.id)
    return [ConversationOut.model_validate(c) for c in conversations]


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> ConversationDetailOut:
    conversation = await conversations_repo.get_owned(
        session, user.id, conversation_id, with_messages=True
    )
    if conversation is None:
        # Ownership miss == nonexistent id, deliberately indistinguishable.
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationDetailOut.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> Response:
    if not await conversations_repo.delete_owned(session, user.id, conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    await session.commit()
    return Response(status_code=204)
