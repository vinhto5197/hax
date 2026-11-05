"""Hand-rolled Anthropic tool-use loop behind /api/chat.

Streams `messages.stream(tools=…)` in a loop: forward text deltas, run requested
tools from the registry, feed results back, repeat until the model stops asking
(or MAX_ITERS). Yields structured events — `{"content": …}` deltas,
`{"status": …}` tool-activity notes, and `{"sources": […]}` provenance after
a tool that returned ToolOutput — that the route serializes to SSE. Sources
are user-facing only: the model receives ToolOutput.text and nothing else.
"""

import logging
import os
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import aclosing
from typing import Any, TypedDict, cast

from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam, ToolResultBlockParam

from packages.core.agent.tools import TOOLS, Source, ToolContext, ToolOutput

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5")
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "32000"))

_client = AsyncAnthropic()

# Hard cap on tool-use iterations per turn.
MAX_ITERS = 5


# The two optional observers below are for callers that measure a turn (the
# eval runner, evals/); the chat route passes neither, so what it streams and
# persists never depends on them. They run inline and are not guarded: an
# observer's exception is the observer's bug and ends the turn.
class Usage(TypedDict):
    model: str
    input: int
    output: int
    cache_read: int
    cache_write: int


class ToolResult(TypedDict):
    name: str
    input: dict
    output: str  # exactly the text the model receives
    is_error: bool


FINAL_ANSWER_PROMPT = (
    "You have reached the tool-use limit for this turn — no more tool calls are "
    "available. Answer the user's question now using only what you have gathered "
    "so far. Be explicit about uncertainty: if the results are incomplete, say "
    "plainly what you could not verify and that your answer may be wrong."
)

_EPHEMERAL = {"type": "ephemeral"}  # 5-minute prompt cache


def _cache_last(messages: list[MessageParam]) -> list[MessageParam]:
    """Prompt-cache breakpoint on the last message's last content block: one
    marker caches everything before it (tools + system + conversation), so each
    call re-reads the growing prefix at ~0.1x. Returns a shallow copy; the
    caller's list is never mutated."""
    if not messages:
        return messages
    last: dict[str, Any] = dict(messages[-1])
    content = last["content"]
    if isinstance(content, str):
        last["content"] = [
            {"type": "text", "text": content, "cache_control": _EPHEMERAL}
        ]
    else:
        blocks = [dict(b) for b in content]
        blocks[-1] = {**blocks[-1], "cache_control": _EPHEMERAL}
        last["content"] = blocks
    # Same role, only the content's blocks gain cache_control: still a
    # MessageParam, which a per-block-type TypedDict copy cannot express.
    return [*messages[:-1], cast(MessageParam, last)]


def _report_usage(
    iteration: str,
    model: str,
    usage: Any,
    on_usage: Callable[[Usage], None] | None,
) -> None:
    counts: Usage = {
        "model": model,
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "cache_read": usage.cache_read_input_tokens or 0,
        "cache_write": usage.cache_creation_input_tokens or 0,
    }
    logger.info(
        "agentic usage: iter=%s input=%d output=%d cache_read=%d cache_write=%d",
        iteration,
        counts["input"],
        counts["output"],
        counts["cache_read"],
        counts["cache_write"],
    )
    if on_usage is not None:
        on_usage(counts)


async def _run_tool(
    name: str, raw_input: dict, ctx: ToolContext
) -> tuple[str, bool, tuple[Source, ...]]:
    """Dispatch one tool_use to its executor; return (result_text, is_error, sources).

    A bad tool name, invalid input, or an executor exception becomes an error
    result (is_error=True, no sources) rather than a crash, so the model can
    see the failure and recover on the next turn.
    """
    try:
        tool = TOOLS[name]
        parsed = tool.input_model.model_validate(raw_input)
        out = await tool.run(parsed, ctx)
        if isinstance(out, ToolOutput):
            return out.text, False, out.sources
        return out, False, ()
    except Exception as exc:  # noqa: BLE001 — tool faults must not crash the loop
        # Type name only: the message can quote the model-authored arguments.
        logger.warning("agentic tool %s failed: %s", name, type(exc).__name__)
        return f"Error running {name}: {exc}", True, ()


async def stream_completion_agentic(
    messages: list[MessageParam],
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    *,
    ctx: ToolContext,
    tools: bool = True,
    on_usage: Callable[[Usage], None] | None = None,
    on_tool_result: Callable[[ToolResult], None] | None = None,
) -> AsyncIterator[dict]:
    """Run the tool-use loop, yielding {"content": …} / {"status": …} /
    {"sources": …} events.

    tools=False sends no tool schemas, so the model can only answer in prose
    (the demo visitor's mode); the loop then ends after its first iteration.
    """
    # Local copy — the intermediate tool turns appended below are never persisted.
    messages = list(messages)
    tool_schemas = [t.to_anthropic() for t in TOOLS.values()] if tools else []
    # Tracks whether any iteration streamed text, so a new iteration's text gets
    # a separator instead of concatenating into run-ons.
    emitted_text = False
    final: Message | None = None

    async def _call(label: str, schemas: list) -> AsyncGenerator[dict, None]:
        # Streams one model call over the current `messages`, leaving its
        # response in `final`. Callers wrap it in aclosing so a closed turn
        # exits the SDK stream at once, as an inline `async with` would.
        nonlocal emitted_text, final
        kwargs: dict = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": _cache_last(messages),
        }
        if schemas:
            kwargs["tools"] = schemas
        if system is not None:
            kwargs["system"] = system

        async with _client.messages.stream(**kwargs) as stream:
            # Forward every text delta, including pre-tool-call narration.
            first_delta = True
            async for text in stream.text_stream:
                if first_delta and emitted_text:
                    yield {"content": "\n\n"}
                first_delta = False
                emitted_text = True
                yield {"content": text}
            final = await stream.get_final_message()

        _report_usage(label, model, final.usage, on_usage)

    for iteration in range(MAX_ITERS):
        async with aclosing(_call(str(iteration), tool_schemas)) as events:
            async for event in events:
                yield event
        assert final is not None

        if final.stop_reason != "tool_use":
            return  # end_turn — the answer already streamed

        messages.append({"role": "assistant", "content": final.content})
        tool_results: list[ToolResultBlockParam] = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            # .get, not [name]: a hallucinated tool name still yields a status;
            # _run_tool turns it into an is_error result.
            tool = TOOLS.get(block.name)
            yield {"status": tool.label if tool else "Working…"}
            # Argument names, sizes and flags only — never values: tool inputs
            # are model-authored and tool output is the user's document text.
            logger.info(
                "agentic tool_use: iter=%d name=%s input_keys=%s",
                iteration,
                block.name,
                sorted(block.input) if isinstance(block.input, dict) else "?",
            )
            out, is_error, sources = await _run_tool(block.name, block.input, ctx)
            logger.info(
                "agentic tool_result: name=%s is_error=%s out_len=%d sources=%d",
                block.name,
                is_error,
                len(out),
                len(sources),
            )
            if on_tool_result is not None:
                on_tool_result(
                    {
                        "name": block.name,
                        # A copy: block.input is replayed to the model next iteration.
                        "input": dict(block.input)
                        if isinstance(block.input, dict)
                        else {},
                        "output": out,
                        "is_error": is_error,
                    }
                )
            if sources:
                # Provenance for the client; never appended to `messages`.
                yield {"sources": [s.as_dict() for s in sources]}
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": out,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": tool_results})

    # Loop exhausted with the model still requesting tools — it never answered.
    # Without a fallback the turn would be silent (status events aren't
    # persisted), so force one final NO-TOOLS call that must produce prose.
    logger.warning("agentic loop hit MAX_ITERS=%d without finishing", MAX_ITERS)
    yield {"status": "Reached the tool-use limit."}
    messages.append({"role": "user", "content": FINAL_ANSWER_PROMPT})
    async with aclosing(_call("fallback", [])) as events:
        async for event in events:
            yield event
