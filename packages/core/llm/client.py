from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 32000
# DEFAULT_MODEL = "claude-opus-4-7"
# MAX_TOKENS = 64000

_client = AsyncAnthropic()


async def stream_completion(
    messages: list[MessageParam],
    system: str | None = None,
    model: str = DEFAULT_MODEL,
) -> AsyncIterator[str]:
    # system carries the RAG instructions when context was retrieved; omitted
    # (not passed as None) for plain chat so the request stays minimal.
    kwargs: dict = {"model": model, "max_tokens": MAX_TOKENS, "messages": messages}
    if system is not None:
        kwargs["system"] = system
    async with _client.messages.stream(**kwargs) as stream:
        async for text in stream.text_stream:
            yield text
