"""Tunable retrieval + chunking knobs, read from env with sane defaults.

Grouped here so tuning is a **config change, not a code edit** (slice 2b). The
defaults reproduce today's behaviour exactly; nothing here is eval-tuned yet —
picking values needs a labeled Q/A set, which is M5 (see the slice-2b spec).
"""

import os

# --- Retrieval ---------------------------------------------------------------

# Nearest chunks to retrieve and inject into the prompt.
TOP_K = int(os.getenv("RAG_TOP_K", "5"))

# Optional absolute cosine-distance cutoff: drop chunks farther than this so an
# off-topic query returns nothing instead of injecting far, irrelevant chunks.
# `None` (unset) = disabled → keep all top-k (today's behaviour). Choosing a value
# — or a relative/adaptive strategy — is M5 eval work; a cosine cutoff only
# rejects *obviously* far junk, not answer-relevance (that's the v1 reranker).
_max_distance = os.getenv("RAG_MAX_DISTANCE")
MAX_DISTANCE: float | None = float(_max_distance) if _max_distance else None

# --- Chunking (characters; ~1600 chars ≈ 400 tokens, ~12% overlap) -----------

CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1600"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "200"))
