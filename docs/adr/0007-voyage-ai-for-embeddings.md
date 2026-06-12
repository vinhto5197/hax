# 0007 — Voyage AI for embeddings

**Status:** accepted — decision point 4 (access via the LangChain interface) revised by [0009](0009-voyage-sdk-direct-langchain-splitter-only.md)
**Date:** 2026-06-09

## Context

M2 (Data + RAG) needs an embedding model: ingestion embeds document chunks,
and every chat query embeds the user's question for similarity search.

Anthropic — our LLM provider (ADR 0002, 0004) — **does not offer an
embeddings API**. Generation and embeddings must come from different
providers. Anthropic's own documentation recommends Voyage AI as its
embeddings partner.

This choice is unusually sticky: the embedding dimension is frozen into the
Postgres schema (`embedding vector(N)`), and vectors from different models
are not comparable — switching provider or model later means a migration
plus re-embedding the entire corpus. (Mitigation: chunk text is stored
verbatim, so re-embedding is mechanical, just not free.)

## Decision

1. **Voyage AI** is the embedding provider. Model: the current
   general-purpose tier (`voyage-4` family as of writing; `voyage-3.5`
   equivalent) — pin the exact model string when slice 1 lands.
2. **1024 dimensions** (the Voyage default across voyage-3.5 and voyage-4),
   stored as `vector(1024)` with an HNSW index using cosine distance.
   1024 sits comfortably under pgvector's 2000-dim HNSW indexing cap.
3. Documents are embedded with `input_type="document"` and queries with
   `input_type="query"` (Voyage's asymmetric embedding; LangChain's
   `embed_documents` / `embed_query` map to these — see ADR 0008).
4. Access goes through the LangChain embeddings interface so the provider
   remains a one-line swap (plus re-embed) rather than a code rewrite.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **OpenAI `text-embedding-3-*`** | Works fine, but adds an unrelated second LLM vendor purely for embeddings. Voyage is the Anthropic-recommended pairing and benchmarks at least as well. |
| **Local model (sentence-transformers, e.g. bge)** | No API cost or external dependency — attractive — but adds a heavyweight inference dependency to the worker image, is slow on CPU, and is an ops burden v0 doesn't need. **Deferred, not dead:** backlogged as a post-v0 experiment (DEV_BACKLOG → Ideas). |
| **Cohere / others** | No advantage over Voyage for this stack; same second-vendor cost without the Anthropic-pairing rationale. |

## Consequences

**Positive:**

- Strong retrieval quality with the officially recommended Claude pairing —
  a clean architecture story.
- 1024 dims is the default across the current Voyage lineup, so model
  upgrades within Voyage likely avoid schema migrations.
- Asymmetric query/document embedding improves retrieval out of the box.

**Negative / accepted:**

- A second API key (`VOYAGE_API_KEY`) and external dependency — on the
  ingestion path *and* the chat hot path (every query is embedded). A
  Voyage outage degrades chat to non-RAG; graceful fallback is a slice-2
  nicety.
- Query embedding adds one network round-trip of latency to each chat
  message before retrieval. Acceptable; measured, not assumed.
- Vendor lock-in is bounded but real: switching = re-embed the corpus.

## When to revisit

- Post-v0 local-embeddings experiment (cost/quality/latency comparison).
- Voyage model deprecations, or pricing/free-tier changes at slice-1 time.
- Multilingual or domain-specific corpora (Voyage has specialized models).

## Related

- [0004](0004-skip-langchain-in-v0-llm-client.md) — kept LangChain out of v0; M2 is its planned re-entry point.
- [0008](0008-langchain-boundaries-for-rag.md) — where LangChain is (and isn't) used in the RAG stack.
