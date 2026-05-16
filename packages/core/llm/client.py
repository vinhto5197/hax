from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

DEFAULT_MODEL = "claude-opus-4-7"
MAX_TOKENS = 64000

_client = AsyncAnthropic()


async def stream_completion(
    prompt: str, model: str = DEFAULT_MODEL
) -> AsyncIterator[str]:
    async with _client.messages.stream(
        model=model,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            yield text
