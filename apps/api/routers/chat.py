import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from packages.core.llm.client import stream_completion
from packages.core.schemas.chat import ChatRequest

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def chat(payload: ChatRequest) -> StreamingResponse:
    # Nested async generator: closes over `payload` and converts the raw
    # token stream from stream_completion into SSE-formatted lines. Defined
    # here (not in core) so the HTTP wire format stays in the transport layer.
    async def events() -> AsyncIterator[str]:
        async for chunk in stream_completion(payload.prompt):
            # JSON-encode the chunk because LLM tokens can contain newlines,
            # which would otherwise break the SSE event delimiter (\n\n).
            yield f"data: {json.dumps({'content': chunk})}\n\n"
        # Terminator the frontend looks for to know the stream is over.
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # no-cache: prevents proxies/browsers from caching a half-streamed
        # response. keep-alive: keeps the TCP connection open through the
        # whole stream (default for HTTP/1.1 but worth being explicit).
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
