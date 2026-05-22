# 0002 — Use anthropic SDK directly (not Claude Agent SDK)

**Status:** accepted
**Date:** 2026-05-21

## Context

The project needs a Python client to call Claude. Two official paths exist:

1. **`anthropic` SDK** — direct HTTP to `api.anthropic.com`. Authenticates with `ANTHROPIC_API_KEY`. Bills against your Anthropic API credit balance.
2. **`claude-agent-sdk` (Claude Agent SDK)** — wraps Anthropic's bundled Claude Code CLI as a subprocess. Can authenticate with `CLAUDE_CODE_OAUTH_TOKEN` (generated via `claude setup-token`), which bills against the developer's Claude Max subscription programmatic credit pool ($100/month for Max 5x, $200/month for Max 20x as of June 2026's separated billing).

The Max-subscription path looked attractive — a hobby project would consume <5% of the included programmatic budget. We tested both before committing.

## Decision

Use the **`anthropic` SDK directly** with `ANTHROPIC_API_KEY`. Default model `claude-haiku-4-5` for v0 to minimize cost during development.

## Alternatives considered

### Claude Agent SDK with CLAUDE_CODE_OAUTH_TOKEN

**Why rejected after hands-on evaluation:**

| Issue | Detail |
|---|---|
| **CLI subprocess architecture** | The SDK shells out to a bundled Claude Code CLI (Node.js). Each request spawns/relays through this subprocess. Adds 1–2 seconds first-request latency. ~100MB resident memory per CLI instance. Production deploy needs Node.js + the CLI in the container alongside Python. |
| **Project-context bleed-in** | Claude Code automatically loads `CLAUDE.md` from cwd, parent dirs, and `~/.claude/`. When uvicorn ran from the project root, the chat behaved as if the end-user was a developer working on the hax project — responses included unsolicited references to hax's milestones and architecture. Suppressing this requires explicit `system_prompt` + `cwd` overrides. |
| **Streaming is server-buffered** | Even with `include_partial_messages=True`, the bundled CLI buffers the model's response server-side and emits all StreamEvent objects in a single burst at the end. Visually, the chat lands all-at-once instead of streaming. |
| **No control over model / max_tokens / thinking** | `ClaudeAgentOptions` doesn't expose `model`, `max_tokens`, or `thinking`. The CLI uses its own defaults. Behavior depends on whichever Claude Code build is bundled with the installed SDK version. |
| **Provider lock-in** | The Agent SDK is Anthropic-specific. The anthropic SDK is too, but its interface (`messages.stream(model=..., messages=[...])`) maps 1:1 to OpenAI/Gemini/etc., making a future provider swap a single-file change. |

### OpenAI / other Claude clients

**Why rejected:** project explicitly chose Claude as the model (per [CLAUDE.md](../../CLAUDE.md)). The anthropic SDK is the canonical client.

### LangChain's `ChatAnthropic`

**Why rejected:** an additional abstraction layer over the anthropic SDK that doesn't earn its weight for a single chat call. See [0004](0004-skip-langchain-in-v0-llm-client.md).

## Consequences

**Positive:**

- Clean separation of chat product from developer's local Claude Code state
- Direct HTTP — no subprocess; ~200ms first-request latency vs 1–2s
- Explicit control of `model`, `max_tokens`, `thinking`, system prompts
- Token-by-token streaming works correctly via `stream.text_stream`
- Production deploy needs only Python (no Node.js, no bundled CLI)
- Future provider swaps (Gemini, GPT-5, local Llama) are a one-file change

**Negative / accepted:**

- Uses API credits instead of pre-paid Max subscription budget. Cost: ~0.25¢/turn (Haiku) or ~1.3¢/turn (Opus). Trivial for dev; bounded for portfolio demo traffic.
- Adaptive thinking unavailable on Haiku (model limitation), and we dropped it for v0 cost. Re-enable on Opus/Sonnet if quality demands it.
- The Max subscription's $100–$200 monthly programmatic budget goes unused. Acceptable: we'd be using a tiny fraction of it anyway.

## When to revisit

- Adding genuine agentic features (file ops, code execution, tool use) where the Agent SDK's machinery earns its keep
- Production scaling where the subprocess overhead becomes the bottleneck (unlikely; we'd hit other limits first)
- Anthropic deprecates or merges one of the SDKs into the other
