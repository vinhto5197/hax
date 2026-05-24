import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from packages.core.llm.agent_client import stream_completion_agent
from packages.core.schemas.chat import ChatRequest

# Sibling to /chat — same SSE wire format, different LLM backend (Claude Agent
# SDK + CLAUDE_CODE_OAUTH_TOKEN instead of anthropic SDK + ANTHROPIC_API_KEY).
# Kept as a separate route so we can A/B the two paths without touching the
# primary chat flow. See ADR 0002.
router = APIRouter(prefix="/chat-agent-sdk", tags=["chat"])


@router.post("")
async def chat_agent_sdk(payload: ChatRequest) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        async for chunk in stream_completion_agent(payload.prompt):
            yield f"data: {json.dumps({'content': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


"""
curl -N -X POST http://localhost:8000/api/chat-agent-sdk \
    -H 'Content-Type: application/json' \
    -d '{"prompt": "tell me a fable"}'
"""
