# 06. Embeddings and search

Threads: A (agentic LLM systems) · B (full-stack engineering)

## The idea

A language model only knows what it was trained on and what you put in front of it. To answer from a user's own files, hax has to find the few passages that matter and hand them to the model. This is RAG (retrieval-augmented generation: look things up first, then write the answer from what was found).

Finding passages by meaning, not by exact words, uses embeddings. An embedding is a list of numbers that places a piece of text at a point in space, so that texts with similar meaning land near each other. Think of a library where books are shelved by what they are about rather than by title. To search, you turn the question into a point too, then pick the passages closest to it.

## How hax does it

Ingestion turns a file into searchable pieces. The splitter in [`packages/core/rag/splitter.py`](../../packages/core/rag/splitter.py) cuts the text into chunks of about 1,600 characters with 200 characters of overlap, so a sentence that falls on a boundary is less likely to be cut in two.

Each chunk is sent to Voyage AI, an embeddings provider, in [`packages/core/rag/embeddings.py`](../../packages/core/rag/embeddings.py). The model is pinned as `voyage-3.5`, and every vector has 1,024 numbers. Documents are embedded with `input_type="document"` and questions with `input_type="query"`; Voyage treats the two sides differently, which helps a short question match a long passage. The code checks every vector's length and fails loudly on a mismatch, because a wrong size would make every distance meaningless. Each attempt is capped at 15 seconds, with up to two retries, since search runs while a user is waiting.

The vectors live in Postgres, the database that already holds everything else, through pgvector (an extension that adds a vector column type and distance operators). The `chunks` table in [`packages/db/models/chunk.py`](../../packages/db/models/chunk.py) stores the chunk text verbatim, its position, the owner's id and a `vector(1024)` column. An HNSW index (a graph-shaped index that finds near neighbors without comparing against every row) uses cosine distance, a measure of how far apart two vectors point.

Search is [`packages/core/rag/retrieval.py`](../../packages/core/rag/retrieval.py). It first checks that the user has at least one chunk from a document marked `ready`, and skips the paid embedding call if not. Then it embeds the question and runs plain SQL (the database's query language): the user's chunks from ready documents, ordered by cosine distance, top five by default (`RAG_TOP_K`). It opens two short database sessions and holds neither across the Voyage call, so a slow provider cannot tie up a pooled connection (one of the few database connections the app keeps open and shares). There is no reranker and no hybrid keyword search: v0 is the open skeleton and deliberately stays at single-vector retrieval.

## What was decided, and why

Anthropic, the provider behind the chat model, has no embeddings API (an interface one program calls over the network), so embeddings had to come from a second vendor. [ADR 0007](../adr/0007-voyage-ai-for-embeddings.md) picked Voyage because Anthropic's documentation recommends it. It rejected OpenAI's embeddings (an unrelated second language-model vendor just for this), a local model (a heavy dependency, slow on CPU, an ops burden) and Cohere (no advantage). The ADR names the cost plainly: the choice is sticky. The vector size is frozen into the schema (the database's table definitions), and vectors from different models cannot be compared, so switching means re-embedding every chunk. Storing chunk text verbatim keeps that mechanical, though not free.

Keeping vectors in Postgres means no separate vector database to run, and the search can filter by user id in the same query.

How much of LangChain (a popular framework of building blocks for language-model apps) to use was its own decision. [ADR 0008](../adr/0008-langchain-boundaries-for-rag.md) used it for two things: the text splitter, and a wrapper around Voyage. It rejected LangChain's vector store because that store wants to own its own tables and sessions, which fights the project's migrations (versioned scripts that change the tables) and its async database layer (the code that talks to Postgres without blocking while it waits). Retrieval SQL, prompt assembly and generation stayed hand-written, so the parts worth seeing stay visible.

## The episode

ADR 0008 lasted two days. While pinning dependencies, the project found that its open-ended version ranges had quietly resolved to LangChain 1.x. The Voyage wrapper, `langchain-voyageai`, had no release compatible with 1.x, while the splitter the project wanted was on 1.x. Both could not be installed together. Keeping the wrapper would have pulled the whole LangChain stack back to an older major version for one thin class.

[ADR 0009](../adr/0009-voyage-sdk-direct-langchain-splitter-only.md) resolved it in `3bf114c`: LangChain is used for text splitting only, and embeddings call the `voyageai` SDK (Voyage's own client library) directly. Two unused LangChain packages were dropped. ADR 0008 was not edited into agreement; its status changed to "superseded," with a note pointing to 0009, and the reasoning stayed readable. A later update inside ADR 0009 switched to Voyage's async client, because the sync client blocks a thread for the whole network call.

## Look at

- [`packages/core/rag/embeddings.py`](../../packages/core/rag/embeddings.py) — pinned model, asymmetric input types, dimension check, 15-second timeout per attempt
- [`packages/core/rag/splitter.py`](../../packages/core/rag/splitter.py) — chunk size and overlap
- [`packages/db/models/chunk.py`](../../packages/db/models/chunk.py) — `vector(1024)` and the HNSW cosine index
- [`packages/core/rag/retrieval.py`](../../packages/core/rag/retrieval.py) — the search SQL, the skip when nothing is ready
- [ADR 0007](../adr/0007-voyage-ai-for-embeddings.md) — Voyage, 1,024 dimensions, the stickiness
- [ADR 0008](../adr/0008-langchain-boundaries-for-rag.md) — the first LangChain cut, superseded
- [ADR 0009](../adr/0009-voyage-sdk-direct-langchain-splitter-only.md) — splitter only, direct SDK
- [`CLAUDE.md`](../../CLAUDE.md) — v0 stays at naive single-vector retrieval
- `3bf114c` — Voyage SDK directly, LangChain scoped to text splitting
