from functools import partial

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from apps.api.chat_service import (
    SSE_HEADERS,
    event_stream,
    load_history,
    persist_user_turn,
)
from packages.core.llm.client import stream_completion, with_cache_breakpoint
from packages.core.rag.prompt import augment_messages
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
    # RAG: retrieve context for the latest turn and inject it into the prompt.
    # Returns (None, messages) when nothing is retrieved (no docs / Voyage down),
    # so this is a transparent no-op for plain chat. `system` is bound into the
    # stream fn so event_stream's contract is unchanged.
    system, messages = await augment_messages(payload.prompt, messages)
    # Prompt caching: mark the last completed turn so the stable prefix (system +
    # prior history) is cached and re-read next turn at ~0.1x; the volatile RAG +
    # question tail stays uncached. No-op below Haiku's 4096-token minimum. Scoped
    # to this route — the agentic route (slice 3) adds its own tools-aware caching.
    messages = with_cache_breakpoint(messages)
    return StreamingResponse(
        event_stream(
            partial(stream_completion, system=system), messages, conversation_id
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


"""
curl -N -X POST http://localhost:8000/api/chat \
    -H 'Content-Type: application/json' \
    -d '{"prompt": "tell me a fable"}'
"""
