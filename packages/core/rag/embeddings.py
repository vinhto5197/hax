import warnings

from packages.db.models.chunk import EMBEDDING_DIM

# voyageai -> langchain_core -> pydantic's own v1-compat shim warns at import
# time under Python 3.14 (upstream dependency issue, not app code — pydantic
# itself flags its v1 shim as broken there). CI runs pytest -W error, so this
# is scoped to the one import that triggers it; nothing else is silenced.
with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message="Core Pydantic V1 functionality isn't compatible with Python 3.14 "
        "or greater",
        category=UserWarning,
    )
    import voyageai

# voyage-3.5: 1024-dim (matches EMBEDDING_DIM); documents and queries use
# asymmetric input_type values. Always pass model= explicitly — the SDK's own
# fallback default ("voyage-2") is NOT 1024-dim. Switching models means
# re-embedding the corpus (ADR 0007).
VOYAGE_MODEL = "voyage-3.5"

# Chunks per Voyage request (the API caps inputs per call).
_BATCH = 100

# Lazy singleton: importing this module never requires VOYAGE_API_KEY.
_client: voyageai.AsyncClient | None = None


def _get_client() -> voyageai.AsyncClient:
    global _client
    if _client is None:
        _client = voyageai.AsyncClient(max_retries=2)  # reads VOYAGE_API_KEY from env
    return _client


def _check_dim(vectors: list[list[float]]) -> list[list[float]]:
    # Fail loudly on any dimension divergence — a silent mismatch would make
    # every stored distance meaningless.
    bad = next((v for v in vectors if len(v) != EMBEDDING_DIM), None)
    if bad is not None:
        raise ValueError(
            f"Voyage returned a {len(bad)}-dim embedding, "
            f"expected {EMBEDDING_DIM} (model={VOYAGE_MODEL})"
        )
    return vectors


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed chunk texts for storage (input_type='document'), batched.

    Batches run sequentially rather than gathered — gentler on rate limits.
    """
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH):
        batch = texts[i : i + _BATCH]
        result = await _get_client().embed(
            batch, model=VOYAGE_MODEL, input_type="document"
        )
        out.extend(result.embeddings)
    # zip() downstream would silently truncate on a count mismatch — make it loud.
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
    return vectors[0]
