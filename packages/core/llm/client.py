from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

# Haiku for v0 — cheapest model, fine for chat. Bump to claude-opus-4-7 or
# claude-sonnet-4-6 when quality matters more than cost.
DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 32000

_client = AsyncAnthropic()


async def stream_completion(
    prompt: str, model: str = DEFAULT_MODEL
) -> AsyncIterator[str]:
    async with _client.messages.stream(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            yield text
