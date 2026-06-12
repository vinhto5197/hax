# 0009 — Voyage SDK directly; LangChain only for text splitting

**Status:** accepted
**Date:** 2026-06-11
**Supersedes:** [0008](0008-langchain-boundaries-for-rag.md) · refines the embeddings-access detail of [0007](0007-voyage-ai-for-embeddings.md)

## Context

[ADR 0008](0008-langchain-boundaries-for-rag.md) scoped LangChain to two
things: the `RecursiveCharacterTextSplitter` and the embeddings interface
(`langchain-voyageai`'s `VoyageAIEmbeddings`). Retrieval, prompt assembly, and
generation were already hand-rolled.

While pinning dependencies before starting M2 (the unbounded `langchain-*>=0.3.0`
pins had silently resolved to LangChain **1.x** in the dev venv), a hard
incompatibility surfaced:

- `langchain-voyageai` (latest **0.1.3**) requires `langchain-core >=0.3.15,<0.4`.
  There is **no langchain-1.x-compatible release** of it.
- `langchain-text-splitters` (the splitter we want) is on **1.x** and requires
  `langchain-core >=1.2,<2`.

So the LangChain stack cannot be simultaneously "current 1.x for the splitter"
**and** "uses `langchain-voyageai`." Keeping the embeddings wrapper would force
the entire LangChain stack down to the deprecated 0.3.x major — for one thin
wrapper class.

Separately, a review of the broader LangChain footprint confirmed nothing else
in the v0 plan needs it: the vector store is our own pgvector SQL (ADR 0008),
generation is the direct `anthropic` SDK (ADR 0004), and slice-3 tool calling
is a hand-rolled loop on the Anthropic SDK (CLAUDE.md lists complex agent
orchestration as a non-goal). LangChain's headline uses — vector stores and
agent orchestration — are deliberately not used here.

## Decision

1. **LangChain is used for text splitting only** — `langchain-text-splitters`
   (`RecursiveCharacterTextSplitter`), pinned `>=1.1,<2`. `langchain-core` comes
   transitively; it is not a direct dependency.
2. **Embeddings call the `voyageai` SDK directly** (`voyageai>=0.4,<1`):
   `voyageai.Client().embed(texts, model=…, input_type="document"|"query")`.
   This replaces the `langchain-voyageai` wrapper from ADR 0008.
3. **Drop `langchain-anthropic` and `langchain-community`** — unused in the v0
   plan.
4. Retrieval (our SQL), prompt assembly (our function in `packages/core`), and
   generation (direct `anthropic` SDK) remain hand-rolled — unchanged from
   ADR 0008 / 0004.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Pin the whole LangChain stack to 0.3.x** to keep `langchain-voyageai` | Anchors every LangChain dep to a deprecated major to preserve one wrapper class; more churn, against the grain of a project actively built on current libraries. |
| **Drop the splitter too — go fully LangChain-free** | Genuinely considered. The recursive splitter (hierarchical separator fallback + overlap) is the one fiddly, well-tested piece worth a dependency, so it stays — *for now*. Deferred, not dead (see When to revisit). |
| **Keep `langchain-voyageai` (status quo, ADR 0008)** | Impossible alongside a 1.x splitter; the version conflict is the whole reason for this ADR. |

## Consequences

**Positive:**

- The LangChain stack sits cleanly on 1.x with no version entanglement.
- Embeddings access is a single direct SDK call — consistent with the
  hand-rolled ethos already established for retrieval and generation
  (ADR 0004 / 0008), and one fewer abstraction between us and the API.
- Fewer dependencies (`langchain-anthropic` / `langchain-community` gone).

**Negative / accepted:**

- `voyageai` is an external dependency on the chat hot path (already accepted
  in ADR 0007 — every query is embedded).
- `langchain-core` is still pulled transitively for a single class. This is a
  real tax: on the dev venv's Python 3.14, `langchain-core` emits a
  *"Pydantic V1 functionality isn't compatible with Python 3.14"* warning. Pin
  Python to 3.11 + commit a lock file in M5 (already backlogged); if the
  transitive weight/churn worsens, hand-rolling the splitter (next item) gets
  the project to zero LangChain.

## When to revisit

- If `langchain-core`'s transitive weight or churn becomes a recurring problem,
  hand-roll the recursive splitter (~80 lines) and drop LangChain entirely —
  which would supersede this ADR back to ADR 0004's "no LangChain in v0."
- v1+ (private fork): heavier multi-agent orchestration is where LangGraph
  could earn a real evaluation — out of scope for v0.

## Related

- [0008](0008-langchain-boundaries-for-rag.md) — superseded by this ADR.
- [0007](0007-voyage-ai-for-embeddings.md) — Voyage + 1024 dims stands; this ADR
  revises only its decision point 4 (access via the LangChain interface → direct SDK).
- [0004](0004-skip-langchain-in-v0-llm-client.md) — the minimalism ethos this extends.
