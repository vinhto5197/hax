import voyageai

from packages.db.models.chunk import EMBEDDING_DIM

# voyage-3.5: general-purpose, 1024-dim (matches EMBEDDING_DIM). Voyage uses
# ASYMMETRIC embedding — documents and queries use different input_type values,
# which improves retrieval. Switching models means re-embedding the corpus
# (ADR 0007). NB: the model is always passed explicitly below — the SDK's own
# fallback default is "voyage-2" (NOT 1024-dim), so never drop the model= arg.
VOYAGE_MODEL = "voyage-3.5"

# _BATCH is how many CHUNKS go in one Voyage request — NOT a per-chunk size
# (chunk length is the splitter's job). Voyage caps inputs per request, so a
# large file (hundreds of chunks) is sent ~100 at a time instead of one giant
# request, or one request per chunk.
_BATCH = 100

# Lazy singleton so importing this module never requires VOYAGE_API_KEY — the
# key is only needed when an embedding is actually computed. We use the ASYNC
# client (aiohttp under the hood) so embed calls await on the event loop
# directly — no asyncio.to_thread bridge. (The sync client blocks the calling
# thread for the whole network round-trip, so callers previously had to offload
# it to a worker thread to avoid freezing the loop; the async client yields the
# loop natively instead.) max_retries gives the SDK's backoff a budget for
# transient 429/503/timeout blips (default 0 = no retry); Celery task-level
# retries come in slice 2.
_client: voyageai.AsyncClient | None = None


def _get_client() -> voyageai.AsyncClient:
    # `global` so we rebind the module-level singleton (without it, the assignment
    # below would make a throwaway local and the singleton would never stick):
    # created once on first use, then reused every call — one aiohttp connection
    # pool, not rebuilt per embed.
    global _client
    if _client is None:
        _client = voyageai.AsyncClient(max_retries=2)  # reads VOYAGE_API_KEY from env
    return _client


def _check_dim(vectors: list[list[float]]) -> list[list[float]]:
    # Fail loudly if any vector's dimension diverges from the column — a silent
    # mismatch would corrupt the index / make distances meaningless. The generator
    # scans EVERY vector and next() stops at the first bad one (or returns None if
    # all pass) — so a mismatch at any index is caught, not just vectors[0].
    bad = next((v for v in vectors if len(v) != EMBEDDING_DIM), None)
    if bad is not None:
        raise ValueError(
            f"Voyage returned a {len(bad)}-dim embedding, "
            f"expected {EMBEDDING_DIM} (model={VOYAGE_MODEL})"
        )
    return vectors


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed chunk texts for storage (input_type='document'), batched.

    Async (Voyage AsyncClient) — await directly on the event loop. Batches are
    awaited sequentially rather than gathered, so we don't fire every batch at
    the API at once (gentler on rate limits).
    """
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH):
        batch = texts[i : i + _BATCH]
        result = await _get_client().embed(
            batch, model=VOYAGE_MODEL, input_type="document"
        )
        out.extend(result.embeddings)
    # Guard against silent under-indexing: zip(chunks, embeddings) downstream
    # would truncate to the shorter list, so make any count divergence loud.
    if len(out) != len(texts):
        raise ValueError(
            f"Voyage returned {len(out)} embeddings for {len(texts)} inputs"
        )
    return _check_dim(out)


async def embed_query(text: str) -> list[float]:
    """Embed a single query for retrieval (input_type='query'). Async."""
    result = await _get_client().embed([text], model=VOYAGE_MODEL, input_type="query")
    vectors = _check_dim(result.embeddings)
    if not vectors:
        raise ValueError("Voyage returned an empty embeddings response")
    # embed returns one vector per input, in order; we passed [text] (len 1), so
    # unwrap the single query vector. Returns a flat list[float], not [[...]].
    return vectors[0]
