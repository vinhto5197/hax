import os
import tempfile
from collections.abc import AsyncIterator

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


async def stream_completion_agent(prompt: str) -> AsyncIterator[str]:
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
