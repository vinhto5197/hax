from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from apps.api.chat_service import (
    SSE_HEADERS,
    chat_event_stream,
    load_history,
    persist_user_turn,
)
from packages.core.llm.client import stream_completion
from packages.core.schemas.chat import ChatRequest

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def chat(payload: ChatRequest) -> StreamingResponse:
    # Persist the user turn (resolving or lazily creating the conversation)
    # before streaming, so the turn survives an LLM error and we have an id to
    # hand back to the client.
    conversation_id = await persist_user_turn(payload.prompt, payload.conversation_id)
    # Replay the full conversation (history + the turn just persisted) so the
    # LLM sees prior context, not just the latest prompt.
    messages = await load_history(conversation_id)
    return StreamingResponse(
        chat_event_stream(stream_completion, messages, conversation_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


"""
curl -N -X POST http://localhost:8000/api/chat \
    -H 'Content-Type: application/json' \
    -d '{"prompt": "tell me a fable"}'
"""
