# 0008 — LangChain boundaries for RAG

**Status:** superseded by [0009](0009-voyage-sdk-direct-langchain-splitter-only.md)
**Date:** 2026-06-09

> **Superseded 2026-06-11.** The embeddings half of this decision
> (`langchain-voyageai`) proved incompatible with a 1.x LangChain stack —
> see [ADR 0009](0009-voyage-sdk-direct-langchain-splitter-only.md), which keeps
> LangChain for the text splitter only and calls the Voyage SDK directly. The
> hand-rolled retrieval/prompt/generation boundaries below still hold.

## Context

ADR 0004 deferred LangChain with an explicit re-entry condition: "M2 begins
(data + RAG): introduce LangChain for retrieval chains." M2 is here, so the
question is no longer *whether* but *how much* LangChain.

LangChain offers pieces at every layer of RAG: document loaders, text
splitters, embeddings wrappers, vector-store adapters (`PGVector`),
retrievers, and full retrieval chains. Adopting all of it hides the
mechanics; adopting none of it means hand-rolling fiddly text-splitting
logic and a provider-coupled embeddings client.

Constraints that shaped the cut:

- The persistence layer is async SQLAlchemy 2.0 + Alembic-owned schema
  (ADR 0006). LangChain's `PGVector` store wants to own its own tables and
  session handling — it fights both.
- The pgvector SQL (`ORDER BY embedding <=> :vec`, the future
  `WHERE user_id` filter) is exactly the part we want explicit, debuggable,
  and demonstrable.
- Generation is direct anthropic SDK streaming (ADR 0002/0004) and works;
  wrapping it in a chain buys nothing.

## Decision

Use LangChain **only** where the abstraction does real work:

1. **Text splitting** — `RecursiveCharacterTextSplitter`
   (`langchain-text-splitters`). Structure-aware splitting with overlap is
   genuinely fiddly to hand-roll well.
2. **Embeddings interface** — `langchain-voyageai`'s `VoyageAIEmbeddings`
   behind our own thin provider seam in `packages/core/rag/`. This is where
   swap-ability matters most (ADR 0007: switching providers is expensive;
   the interface keeps it a one-line change + re-embed).

Hand-roll the rest:

3. **Retrieval** — explicit SQL through our async SQLAlchemy layer. No
   `PGVector` store, no `.as_retriever()`.
4. **Prompt assembly** — our own function in `packages/core` building the
   system prompt + messages array (history + retrieved chunks).
5. **Generation** — unchanged: direct anthropic SDK streaming.

LangChain types do not leak out of `packages/core/rag/`.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Full LangChain** (PGVector store + retrieval chains/LCEL) | The store owns its own schema/tables (fights Alembic migrations and async sessions); chains add an abstraction layer over a three-step flow that reads fine as plain Python; hides the SQL we want visible. |
| **No LangChain at all** | Re-implement the splitter (error-prone, zero learning value) and hand-write a Voyage client coupled to one provider — for the marginal benefit of dropping deps that are already in `pyproject.toml`. |

## Consequences

**Positive:**

- The expensive-to-change seam (embedding provider) is swappable; the
  cheap-to-change parts (SQL, prompt) stay plain and visible.
- Retrieval SQL composes naturally with the rest of the schema — the M2.5
  `user_id` filter is a one-line WHERE, not an adapter feature request.
- Clear narrative: "LangChain where the abstraction earns its keep,
  explicit code where visibility matters."

**Negative / accepted:**

- We own prompt assembly and retrieval code (small, but ours to maintain).
- Two LangChain integration packages to track (`langchain-text-splitters`,
  `langchain-voyageai`).
- If future needs call for LangChain's higher-level agent/runnable machinery,
  this ADR gets revisited rather than extended silently.

## Related

- [0004](0004-skip-langchain-in-v0-llm-client.md) — the deferral this ADR resolves; its core decision (direct SDK for generation) **stands**.
- [0006](0006-async-sqlalchemy-asyncpg-alembic.md) — the persistence stack the `PGVector` store would have fought.
- [0007](0007-voyage-ai-for-embeddings.md) — the provider behind the embeddings interface.
