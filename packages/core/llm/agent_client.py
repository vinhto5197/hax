import os
import tempfile
from collections.abc import AsyncIterator

from anthropic.types import MessageParam
from claude_agent_sdk import (
    ClaudeAgentOptions,
    StreamEvent,
    query,
)

# Force the OAuth token path:
#   - The bundled CLI prefers ANTHROPIC_API_KEY over CLAUDE_CODE_OAUTH_TOKEN when
#     both are visible. ClaudeAgentOptions.env is *merged* into os.environ (not a
#     replacement), so we must explicitly blank ANTHROPIC_API_KEY to evict the
#     parent process's value.
_OAUTH_TOKEN = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")

# Force a clean subprocess context:
#   - setting_sources=[]: disable loading of ~/.claude/ (user) and ./CLAUDE.md
#     (project) settings. Without this the CLI bakes ~22k tokens of hax context
#     into every input.
#   - cwd=tempfile.gettempdir(): even with setting_sources off, point the CLI
#     at a directory with no CLAUDE.md anywhere in its parent chain — belt to
#     the suspenders of setting_sources.
#   - system_prompt="": override the default Claude Code persona.
#   - allowed_tools=[] + max_turns=1: no tools, single turn — pure chat.
# See ADR 0002 for the full set of tradeoffs vs the direct anthropic SDK.
_OPTIONS = ClaudeAgentOptions(
    system_prompt="",
    allowed_tools=[],
    max_turns=1,
    setting_sources=[],
    cwd=tempfile.gettempdir(),
    include_partial_messages=True,
    env={
        "CLAUDE_CODE_OAUTH_TOKEN": _OAUTH_TOKEN,
        "ANTHROPIC_API_KEY": "",
    },
)


def _render_transcript(messages: list[MessageParam]) -> str:
    """Flatten an Anthropic messages array into a single prompt string.

    The Agent SDK's query() is prompt-shaped (one string per call) and keeps
    its own session state on disk, which doesn't fit our stateless
    replay-from-Postgres model: adopting the SDK's resume machinery would
    make its session files a second source of truth for history that can
    silently diverge from the DB (temp cleanup, new machine -> amnesia
    returns while Postgres still has everything). Rendering prior turns as a
    tagged transcript keeps Postgres canonical and the route stateless, at
    the cost of losing the structured role framing the primary route gets.
    Acceptable for an A/B route; revisit if it ever graduates (ADR 0002).

    A user-typed literal '</history>' could escape the transcript block —
    inherent to flattening; tolerated here, impossible on the primary route.
    """
    *history, current = messages
    current_text = current["content"]
    assert isinstance(current_text, str)  # we only ever build text-content messages
    if not history:
        # First turn: bare prompt, byte-identical to the pre-history behavior.
        return current_text
    turns = "\n".join(f"<{m['role']}>\n{m['content']}\n</{m['role']}>" for m in history)
    return (
        "The following is your conversation with the user so far:\n\n"
        f"<history>\n{turns}\n</history>\n\n"
        "Continue the conversation. Reply to the user's latest message:\n\n"
        f"{current_text}"
    )


async def stream_completion_agent(messages: list[MessageParam]) -> AsyncIterator[str]:
    prompt = _render_transcript(messages)

    # With include_partial_messages=True, the SDK emits StreamEvent objects
    # carrying the raw Anthropic API stream events (content_block_delta, etc.)
    # as tokens arrive. The terminal AssistantMessage is the *complete* message
    # — yielding from it lands all-at-once. We forward only the delta text from
    # StreamEvent and ignore the AssistantMessage to get true token streaming.
    async for message in query(prompt=prompt, options=_OPTIONS):
        if not isinstance(message, StreamEvent):
            continue
        event = message.event
        if event.get("type") != "content_block_delta":
            continue
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            if text:
                yield text
