from functools import partial

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from apps.api.chat_service import (
    SSE_HEADERS,
    chat_event_stream,
    load_history,
    persist_user_turn,
)
from packages.core.llm.agent_client import stream_completion_agent
from packages.core.rag.prompt import augment_messages
from packages.core.schemas.chat import ChatRequest

# Sibling to /chat — same SSE wire format, different LLM backend (Claude Agent
# SDK + CLAUDE_CODE_OAUTH_TOKEN instead of anthropic SDK + ANTHROPIC_API_KEY).
# Kept as a separate route so we can A/B the two paths without touching the
# primary chat flow. See ADR 0002.
router = APIRouter(prefix="/chat-agent-sdk", tags=["chat"])


@router.post("")
async def chat_agent_sdk(payload: ChatRequest) -> StreamingResponse:
    conversation_id = await persist_user_turn(payload.prompt, payload.conversation_id)
    # Same replay as the primary route; stream_completion_agent flattens the
    # array into a transcript prompt (the Agent SDK is prompt-shaped).
    messages = await load_history(conversation_id)
    # RAG parity with /chat: inject retrieved context into the latest user turn
    # (which flows into the transcript) and carry the instruction via `system`,
    # bound into the stream fn so chat_event_stream's contract stays unchanged.
    system, messages = await augment_messages(payload.prompt, messages)
    return StreamingResponse(
        chat_event_stream(
            partial(stream_completion_agent, system=system), messages, conversation_id
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


"""
curl -N -X POST http://localhost:8000/api/chat-agent-sdk \
    -H 'Content-Type: application/json' \
    -d '{"prompt": "tell me a fable"}'
"""
