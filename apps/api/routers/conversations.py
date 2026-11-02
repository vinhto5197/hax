from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import CurrentUser, current_user
from apps.api.chat_service import claim_for_retry
from apps.api.demo import enforce_turn_cap
from apps.api.deps import get_session
from apps.api.routers.chat import read_about, start_reply
from apps.api.turns import stop_turn
from packages.core.schemas.chat import RetryRequest
from packages.core.schemas.conversation import (
    ConversationDetailOut,
    ConversationOut,
    MessageOut,
)
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
    found = await conversations_repo.get_owned_detail(session, user.id, conversation_id)
    if found is None:
        # Ownership miss == nonexistent id, deliberately indistinguishable.
        raise HTTPException(status_code=404, detail="conversation not found")
    conversation, replying = found
    return ConversationDetailOut(
        **ConversationOut.model_validate(conversation).model_dump(),
        messages=[MessageOut.model_validate(m) for m in conversation.messages],
        replying=replying,
    )


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


@router.post("/{conversation_id}/stop", status_code=204)
async def stop_conversation_reply(
    conversation_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> Response:
    # Ownership before the registry: turns are keyed by conversation only, so
    # this check is what keeps a stop from crossing users. 204 whether or not
    # a turn was running here: stopping is idempotent.
    if await conversations_repo.get_owned(session, user.id, conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    stop_turn(conversation_id)
    return Response(status_code=204)


@router.post(
    "/{conversation_id}/retry",
    responses={
        403: {"description": "demo_limit: sign up to continue"},
        409: {
            "description": "a reply is already in progress in this"
            " conversation, or nothing_to_retry / already_answered: the"
            " conversation no longer ends where the page saw it end"
        },
    },
)
async def retry_reply(
    conversation_id: UUID,
    payload: RetryRequest,
    user: CurrentUser = Depends(current_user),
) -> StreamingResponse:
    # The same order as a send: a retry costs a full reply, so it spends a
    # visitor's turn, counted per request like a refused send.
    await enforce_turn_cap(user)
    about = await read_about(user)
    claimed_at = await claim_for_retry(
        conversation_id, user.id, payload.after, payload.replace
    )
    return await start_reply(conversation_id, claimed_at, user, about, payload.model)
