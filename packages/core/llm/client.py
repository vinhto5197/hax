import logging
import os
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

logger = logging.getLogger(__name__)

# Env-tunable (LLM_MODEL / LLM_MAX_TOKENS); central config comes in M5. Haiku is a
# fine default for grounded RAG Q&A (cheap + fast, and RAG supplies the knowledge
# the model would otherwise lack); switch to a larger model for reasoning-heavy
# work by setting LLM_MODEL.
DEFAULT_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5")
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "32000"))

_client = AsyncAnthropic()


def with_cache_breakpoint(messages: list[MessageParam]) -> list[MessageParam]:
    """Mark the last *completed* turn for prompt caching (main chat route).

    Prompt caching is a prefix match: a `cache_control` breakpoint caches every
    byte from the start (tools -> system -> messages) up to that block, and the
    next request re-reads the longest identical prefix at ~0.1x. We only choose
    where the *write* boundary sits; reads are automatic.

    Returns messages unchanged when there's no completed turn yet (first turn) or
    when `messages[-2]` isn't string content (defensive — a future tool-use path
    would place its own breakpoint). Otherwise returns a shallow copy whose
    second-to-last message carries the breakpoint; one marker there caches system
    + all prior history as a single prefix.

    Why messages[-2], not messages[-1]: messages[-1] is the *current* turn, and on
    the RAG path augment_messages has prepended retrieved <context> to it —
    context that is NOT persisted (load_history replays the raw question). So the
    augmented messages[-1] never recurs byte-identically next turn; caching it
    would pay the write premium and never read back (auto-cache-on-a-volatile-tail
    miss). messages[-2] (the frozen previous turn) is the last block guaranteed to
    reappear unchanged, so it's the real prefix boundary. Haiku 4.5 only caches
    prefixes >= 4096 tokens; shorter conversations silently don't cache
    (cache_creation_input_tokens: 0) — expected, not a bug.
    """
    if len(messages) < 2:
        return messages
    prev = messages[-2]
    content = prev["content"]
    if not isinstance(content, str):
        return messages
    marked = {
        **prev,
        "content": [
            {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
        ],
    }
    return [*messages[:-2], marked, messages[-1]]


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
        # Cache observability: log what the prefix cache did this request. Reads
        # cost ~0.1x, writes ~1.25x; `input` is the uncached remainder only, so
        # total prompt = input + cache_read + cache_write. Zeros until the cached
        # prefix clears Haiku's 4096-token minimum (short chats don't cache).
        usage = (await stream.get_final_message()).usage
        logger.info(
            "chat usage: input=%d output=%d cache_read=%d cache_write=%d",
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_input_tokens or 0,
            usage.cache_creation_input_tokens or 0,
        )
