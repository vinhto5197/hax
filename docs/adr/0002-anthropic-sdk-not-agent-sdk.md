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

**Update 2026-05-22:** the Agent SDK path is kept alive as a sibling route (`POST /api/chat-agent-sdk`, backed by `packages/core/llm/agent_client.py`) so the two backends can be A/B'd at runtime. The chat UI exposes a backend selector dropdown — defaulted to **Claude Agent SDK** while the Max subscription's interactive cap is the de-facto budget for v0 dev (pre-June-2026 billing model). The primary anthropic SDK path stays available behind the same dropdown; nothing about the decision below changes. The sibling route exists for empirical comparison, not as a fallback.

**Subprocess hardening required.** Three independent footguns surfaced when wiring the sibling route:

1. **Auth precedence** — the bundled CLI prefers `ANTHROPIC_API_KEY` over `CLAUDE_CODE_OAUTH_TOKEN`. `ClaudeAgentOptions.env` is *merged* with `os.environ` (transport/subprocess_cli.py line 430-434), not a replacement. Fix: pass `env={"CLAUDE_CODE_OAUTH_TOKEN": ..., "ANTHROPIC_API_KEY": ""}` to evict the inherited key.
2. **Context bleed** — `system_prompt=""` alone does not stop the CLI loading `CLAUDE.md` (project) and `~/.claude/` (user) settings. Empirically observed at ~22k input tokens per request. Fix: set `setting_sources=[]` to disable both, and set `cwd=tempfile.gettempdir()` so the CLI's upward CLAUDE.md walk finds nothing.
3. **Tool / loop hygiene** — `allowed_tools=[]` + `max_turns=1` keep the model from emitting `tool_use` blocks and prevent multi-turn loops.

After all three mitigations: same model, ~50 input tokens (vs ~22k), billed against Max instead of API.

**Update 2026-06-24 — RAG parity on the sibling route.** The M2 RAG flow was first wired into the primary `/api/chat` route only; the sibling route lagged (de-amnesia but no retrieval). It now has parity. Mechanism difference, since the Agent SDK is prompt-shaped: the retrieved context is injected into the latest user turn upstream (`augment_messages`) and rides into the flattened transcript for free, while the `RAG_SYSTEM` instruction travels via the SDK's `system_prompt`. Because `system_prompt=""` is a per-call option, the route now builds options dynamically — `dataclasses.replace(_OPTIONS, system_prompt=RAG_SYSTEM)` when context was retrieved, else the empty-persona `_OPTIONS` unchanged. (This refines the "no control over system prompt" note below: we *do* set it, dynamically, per request.) Verified e2e 2026-06-24 — grounded answer cites the source document; out-of-corpus degrades to general knowledge with the distinction made explicit.

**Glossary — "the harness":** when this ADR talks about the Agent SDK's "harness," it means the local Node.js loop that wraps every model call. A bare LLM is `prompt → text`. The harness adds: (1) context assembly (gluing the persona system prompt, `CLAUDE.md` files, tool descriptions, and conversation history into the request); (2) the agentic loop (inspect the model's response for `tool_use` blocks → execute the tool locally → append the result → re-request the model, repeating until either pure prose comes back or `max_turns` is hit); (3) policy gates (`allowed_tools`, `max_turns`, `permission_mode`). The model never executes anything — it only emits text, including text that looks like tool calls. The *harness* is what turns that text into a file read or a bash command on your machine. For a single-shot chat product, every layer of the harness is overhead: we want `prompt → text`, not the loop. That's the structural reason this ADR prefers the bare `anthropic` SDK.

**Empirical layer-by-layer test (run 2026-05-22):** to confirm what each mitigation actually does, we toggled `setting_sources` and `cwd` independently while leaving `system_prompt=""`, `allowed_tools=[]`, and `max_turns=1` fixed. Findings:

| `setting_sources` | `cwd` | Result | What's happening |
|---|---|---|---|
| `["user","project"]` (default) | `/tmp` | Clean response, no hax bleed | Project loader walks up from `/tmp`, finds no `CLAUDE.md`. User loader checks `~/.claude/CLAUDE.md` — which doesn't exist on this dev machine. Lucky empty load. |
| `[]` | `/tmp` | Clean response, no hax bleed (recommended config) | Both loaders disabled outright; cwd is innocuous. Belt-and-suspenders. |
| `["user","project"]` (default) | `/Users/vinh/workspace/hax` | hax context bleeds in | Project loader finds `hax/CLAUDE.md`, concatenates into the system prompt. |
| `[]` | `/Users/vinh/workspace/hax` | **`Reached maximum number of turns (1)`** error | Settings load is off, but cwd looks like a code repo. Model decides "the user is asking about this codebase" and emits a `tool_use` block (Read/Glob). The harness can't execute it (`allowed_tools=[]`) and can't recover (`max_turns=1`), so it aborts. |

The fourth case is the cautionary tale: `setting_sources=[]` alone is not enough. If the subprocess cwd looks like a code repo, the model still reaches for tools, and the harness deadlocks against `max_turns=1`. Mitigation: also pass a non-repo `cwd`.

**Tone shift is real and traces to project `CLAUDE.md`, not user plugins.** Repeated trials produced a consistent pattern across the two settings-on configurations:

- `setting_sources` default, `cwd=/Users/vinh/workspace/hax` → confident, action-oriented voice
- `setting_sources` default, `cwd=tempfile.gettempdir()` → hedged, defensive baseline voice

The variable that flipped was `cwd`, not `setting_sources`. Causal chain: `setting_sources` includes `"project"` by default, which makes the CLI walk *upward from cwd* looking for `CLAUDE.md`. When cwd is the hax repo, the walk finds `hax/CLAUDE.md` and concatenates it into the system prompt. When cwd is `/tmp`, the walk finds nothing. The hax `CLAUDE.md` is written in confident product-doc voice (milestones, "ships the complete vertical slice," "lean toward interview-ready narratives"), and the model adopts that register — even when answering a generic question about the word "hax" rather than the project. The CLAUDE.md influences the model's *voice*, not just its *topic knowledge*.

The user-level plugin stack (`~/.claude/settings.json` → `superpowers`, `frontend-design`, etc.) likely amplifies the effect, but is not the load-bearing piece: cwd alone moves the dial.

Two implications worth knowing:

1. **The Agent SDK's behavior is not just a function of code we write** — it depends on what `CLAUDE.md` files (and `~/.claude/` settings) the developer happens to have near their working directory. Same code, different cwd, different voice. For a product backend this is unacceptable. `setting_sources=[]` and a non-repo `cwd` together make the output machine- and location-independent.
2. **In prod (Docker)**, the container's working directory will contain the repo (so `CLAUDE.md` is reachable from cwd) but won't have `~/.claude/`. Without `setting_sources=[]` + a scrubbed cwd, prod responses would inherit hax's product-doc tone uninvited. The explicit overrides close this leak.

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
