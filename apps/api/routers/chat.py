from functools import partial

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from apps.api.chat_service import (
    SSE_HEADERS,
    event_stream,
    load_history,
    persist_user_turn,
)
from packages.core.agent.harness import DEFAULT_MODEL, stream_completion_agentic
from packages.core.schemas.chat import ChatRequest

router = APIRouter(prefix="/chat", tags=["chat"])

# Behaviour prompt for the chat route. BEHAVIOUR only — NOT a tool inventory:
# the model learns what tools exist and when to use each from the registry (each
# Tool's `description`, sent via tools=…), so listing them here would be redundant
# and would drift as tools are added. Kept stable (cache-friendly).
AGENTIC_SYSTEM = (
    "You are a helpful assistant. Use the available tools whenever they make your "
    "answer more accurate, and feel free to use several across turns. When you "
    "answer from the user's uploaded documents, mention which document(s) you "
    "used; if they don't contain the answer, say so plainly."
)


@router.post("")
async def chat(payload: ChatRequest) -> StreamingResponse:
    # Persist the user turn (resolving or lazily creating the conversation) before
    # streaming, so the turn survives an error and we have an id for the client.
    conversation_id = await persist_user_turn(payload.prompt, payload.conversation_id)
    # Replay prior turns (de-amnesia). Retrieval is NOT injected here — the model
    # calls the search_documents tool itself when the corpus looks relevant.
    messages = await load_history(conversation_id)
    # Optional per-request model override (UI dropdown); else the default.
    model = payload.model or DEFAULT_MODEL
    # Bind system + model into the harness; event_stream drives it and serializes
    # its {"content"}/{"status"} events to SSE, persisting only the content.
    event_fn = partial(stream_completion_agentic, system=AGENTIC_SYSTEM, model=model)
    return StreamingResponse(
        event_stream(event_fn, messages, conversation_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


"""
curl -N -X POST http://localhost:8000/api/chat \
    -H 'Content-Type: application/json' \
    -d '{"prompt": "what is 19381 * 22.5?"}'
"""
