# 0004 — Skip LangChain in v0 LLM client

**Status:** accepted
**Date:** 2026-05-21

## Context

The original project scaffolding included LangChain dependencies in `pyproject.toml`:

```toml
"langchain-core>=0.3.0",
"langchain-anthropic>=0.3.0",
"langchain-community>=0.3.0",
```

LangChain is a popular Python framework for LLM application orchestration. It offers `ChatAnthropic` (and similar wrappers for other providers), prompt templates, output parsers, retrieval chains, and agent frameworks. The intent was to use it as the unified LLM layer.

The first cut of `packages/core/llm/client.py` used `langchain_openai.ChatOpenAI` with a 58-line implementation including message conversion (`HumanMessage` ↔ `AIMessage`), content-type unions (`str | list[ContentBlock]`), and adapter logic.

For v0's stateless single-turn chat, this was disproportionate.

## Decision

For v0:

1. **Use the `anthropic` SDK directly** in `packages/core/llm/client.py`. ~22 lines, no abstraction layer.
2. **Keep LangChain in `pyproject.toml`** for future use (M2 RAG will need it for text splitters, vector store abstractions, retrieval chains).
3. **Re-introduce LangChain when M2 lands** and there's an actual orchestration need.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Keep LangChain in client.py** | Adds ~30 lines of glue code (message conversion, content-type handling) for what's already a 22-line direct SDK call. No payoff in v0. |
| **Remove LangChain from pyproject entirely** | M2 RAG will need it within weeks. Removing then re-adding churns the lockfile. The dev-environment cost of including unused deps is small. |
| **Hand-roll the abstractions LangChain provides** | RAG-era abstractions (text chunking, embedding interfaces, vector store adapters, retrieval chains) are non-trivial. Reinventing them costs more than including LangChain. |

## Consequences

**Positive:**

- 22-line `client.py` is easy to read and debug
- Direct streaming via `stream.text_stream` — no LangChain adapter between us and the SDK's streaming primitives
- Clear separation: when M2 work begins, we'll know exactly where to introduce the LangChain layer
- No premature abstraction; the v0 code answers "what does it do?" without first answering "what framework is this in?"

**Negative / accepted:**

- LangChain sits in `pyproject.toml` unused for now. Minor `pip install` overhead; no runtime cost.
- When LangChain is reintroduced for M2, we'll write new code rather than evolve current code. Acceptable: the LLM client's M2 role (orchestrating retrieval + generation) is structurally different from v0's role (single-call streaming).

## When to revisit

- M2 begins (data + RAG): introduce LangChain for retrieval chains. Direct anthropic streaming stays for the final generation step inside the chain.
- Tool use / agentic features arrive: evaluate LangChain's agent abstractions vs writing our own loop.

## Related

- [0002](0002-anthropic-sdk-not-agent-sdk.md) — choosing the direct anthropic SDK over Claude Agent SDK. Both decisions reduce abstraction in v0.
