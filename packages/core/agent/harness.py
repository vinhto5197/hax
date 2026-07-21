"""Hand-rolled Anthropic tool-use loop for the agentic route (M2 slice 3).

Drives `messages.stream(tools=…)` in a loop: forward text deltas, run any tools
the model requests from the registry, feed the results back, and repeat until the
model stops asking for tools (or MAX_ITERS is hit). Yields structured events —
`{"content": …}` text deltas and `{"status": …}` tool-activity notes — that the
route serializes to SSE. Native Anthropic tool use, not MCP.
"""

import logging
import os
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

from packages.core.agent.tools import TOOLS

logger = logging.getLogger(__name__)

# Env-tunable (LLM_MODEL / LLM_MAX_TOKENS); central config comes in M5. Haiku is
# a fine default for grounded, tool-assisted Q&A (cheap + fast; the tools supply
# facts the model would otherwise lack); switch models per request via
# ChatRequest.model or globally via LLM_MODEL.
DEFAULT_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5")
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "32000"))

_client = AsyncAnthropic()

# Cap the tool-use loop so a misbehaving model can't spin forever. The seed of
# the v1 agent "control policy" (termination) — today just a hard iteration cap.
MAX_ITERS = 5

# On loop exhaustion the model has only ever stopped at tool_use — it never
# produced an answer. This instruction drives one final NO-TOOLS call so the turn
# always ends in prose; defensive by design (the gathered results are incomplete).
FINAL_ANSWER_PROMPT = (
    "You have reached the tool-use limit for this turn — no more tool calls are "
    "available. Answer the user's question now using only what you have gathered "
    "so far. Be explicit about uncertainty: if the results are incomplete, say "
    "plainly what you could not verify and that your answer may be wrong."
)

_EPHEMERAL = {"type": "ephemeral"}  # 5-minute prompt cache


def _cache_last(messages: list[MessageParam]) -> list[MessageParam]:
    """Put a cache breakpoint on the last message's last content block, so each
    loop iteration re-reads the growing conversation prefix at ~0.1x instead of
    re-sending it whole. Shallow copy; the caller's list is unchanged.

    Unlike /api/chat (which marks messages[-2] because its RAG-augmented last turn
    never recurs), the agentic loop injects nothing per-request into messages —
    every message recurs next iteration — so we mark the last one.
    """
    if not messages:
        return messages
    last = dict(messages[-1])
    content = last["content"]
    if isinstance(content, str):
        last["content"] = [
            {"type": "text", "text": content, "cache_control": _EPHEMERAL}
        ]
    else:
        blocks = [dict(b) for b in content]
        blocks[-1] = {**blocks[-1], "cache_control": _EPHEMERAL}
        last["content"] = blocks
    return [*messages[:-1], last]


async def _run_tool(name: str, raw_input: dict) -> tuple[str, bool]:
    """Dispatch one tool_use to its executor; return (result_text, is_error).

    A bad tool name, invalid input, or an executor exception becomes an error
    result (is_error=True) rather than a crash, so the model can see the failure
    and recover on the next turn.
    """
    try:
        tool = TOOLS[name]
        parsed = tool.input_model.model_validate(raw_input)
        return await tool.run(parsed), False
    except Exception as exc:  # noqa: BLE001 — tool faults must not crash the loop
        logger.warning("agentic tool %s failed: %s", name, exc, exc_info=True)
        return f"Error running {name}: {exc}", True


async def stream_completion_agentic(
    messages: list[MessageParam],
    system: str | None = None,
    model: str = DEFAULT_MODEL,
) -> AsyncIterator[dict]:
    """Run the tool-use loop, yielding {"content": …} / {"status": …} events."""
    # Local copy — we append the intermediate tool turns (which the route does
    # NOT persist), so we don't mutate the caller's list.
    messages = list(messages)
    tool_schemas = [t.to_anthropic() for t in TOOLS.values()]
    # Whether any prior iteration streamed text — used to insert a separator so
    # per-iteration narration and the final answer don't concatenate into
    # run-ons ("Let me check.Based on...") in the stream AND the persisted turn.
    emitted_text = False

    for iteration in range(MAX_ITERS):
        kwargs: dict = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            # One breakpoint on the last message caches EVERYTHING before it —
            # tools + system + the whole conversation-so-far — so each loop
            # iteration re-reads that growing prefix at ~0.1x instead of re-sending
            # it whole. A separate tools+system breakpoint would only add
            # cross-conversation cache sharing (many distinct chats reusing one
            # tools+system entry) — a scale optimisation, deferred to v1.
            "messages": _cache_last(messages),
            "tools": tool_schemas,
        }
        if system is not None:
            kwargs["system"] = system

        async with _client.messages.stream(**kwargs) as stream:
            # Forward every text delta, including the model's intermediate
            # reasoning before a tool call — we do not suppress it.
            first_delta = True
            async for text in stream.text_stream:
                if first_delta and emitted_text:
                    yield {"content": "\n\n"}  # separate from the prior iteration
                first_delta = False
                emitted_text = True
                yield {"content": text}
            final = await stream.get_final_message()

        # Cache observability (like /api/chat): reads ~0.1x, writes ~1.25x; input
        # is the uncached remainder. Expect cache_read>0 from iteration 1 onward.
        usage = final.usage
        logger.info(
            "agentic usage: iter=%d input=%d output=%d cache_read=%d cache_write=%d",
            iteration,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_input_tokens or 0,
            usage.cache_creation_input_tokens or 0,
        )

        if final.stop_reason != "tool_use":
            return  # end_turn (or max_tokens) — the final answer already streamed

        # The model requested one or more tools. Replay its assistant turn (the
        # tool_use blocks), run each tool, feed the results back as a user turn.
        messages.append({"role": "assistant", "content": final.content})
        tool_results: list[dict] = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            # `TOOLS.get` (not [name]) so a hallucinated tool name still yields a
            # status; _run_tool then turns the bad name into an is_error result.
            tool = TOOLS.get(block.name)
            yield {"status": tool.label if tool else "Working…"}
            logger.info(
                "agentic tool_use: iter=%d name=%s input=%s",
                iteration,
                block.name,
                block.input,
            )
            out, is_error = await _run_tool(block.name, block.input)
            logger.info(
                "agentic tool_result: name=%s is_error=%s out=%r",
                block.name,
                is_error,
                out[:200],
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": out,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": tool_results})

    # Fell out of the loop without an end_turn: every call so far stopped at
    # tool_use, so the model never produced an answer — without a fallback this
    # turn would be SILENT (status events aren't persisted, and the frontend may
    # ignore them). Force one final call with NO tools so a real answer always
    # streams and persists. The instruction turn is appended to the local copy
    # only (never persisted); consecutive user turns are fine (the API merges).
    logger.warning("agentic loop hit MAX_ITERS=%d without finishing", MAX_ITERS)
    yield {"status": "Reached the tool-use limit."}
    messages.append({"role": "user", "content": FINAL_ANSWER_PROMPT})
    kwargs = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "messages": _cache_last(messages),
    }
    if system is not None:
        kwargs["system"] = system
    async with _client.messages.stream(**kwargs) as stream:
        first_delta = True
        async for text in stream.text_stream:
            if first_delta and emitted_text:
                yield {"content": "\n\n"}
            first_delta = False
            emitted_text = True
            yield {"content": text}
        final = await stream.get_final_message()
    usage = final.usage
    logger.info(
        "agentic usage: iter=fallback input=%d output=%d cache_read=%d cache_write=%d",
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_input_tokens or 0,
        usage.cache_creation_input_tokens or 0,
    )
