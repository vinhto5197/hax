import logging
import os
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from packages.core.rag.embeddings import embed_query
from packages.db import AsyncSessionLocal
from packages.db.models import Chunk, Document

logger = logging.getLogger(__name__)

TOP_K = int(os.getenv("RAG_TOP_K", "5"))

# Optional absolute cosine-distance cutoff; unset = keep all top-k. Note a
# cosine cutoff only rejects obviously-far junk, not answer-irrelevance —
# real relevance ranking is a reranker's job.
_max_distance = os.getenv("RAG_MAX_DISTANCE")
MAX_DISTANCE: float | None = float(_max_distance) if _max_distance else None


class RetrievalUnavailable(Exception):
    """Search could not run (Voyage, the database). Distinct from finding
    nothing: search_documents lets it propagate and the agent harness
    (_run_tool) turns it into an error result, so the model never tells a
    member their documents lack something it could not search."""

    def __init__(self, message: str = "document search is temporarily unavailable"):
        super().__init__(message)


@dataclass
class RetrievedChunk:
    content: str
    filename: str
    distance: float  # cosine distance: 0 = identical direction, 2 = opposite
    # Identity for user-facing provenance (the sources footer); the model-facing
    # text is built from content + filename only.
    document_id: uuid.UUID
    chunk_idx: int


async def retrieve(query: str, user_id: uuid.UUID) -> list[RetrievedChunk]:
    """Embed the query and return its k nearest chunks by cosine distance.

    [] means nothing was found, including a user with no ready chunks (the
    paid embed is skipped then). Any fault raises RetrievalUnavailable. Only
    chunks of status='ready' documents are searched — in-flight or failed
    ingests never leak partial chunks (delete-then-insert makes 'ready' imply a
    complete chunk set). Scoped to user_id's chunks (required — identity comes
    from the request, never from the model). RAG_MAX_DISTANCE, if set, drops
    chunks farther than the cutoff.
    """
    try:
        # Two short sessions, none held across the embed call: a slow or
        # stalled embedding request must not pin a pooled connection, or the
        # agent's repeated searches drain the pool for every other request.
        async with AsyncSessionLocal() as session:
            # Skip the paid embed unless at least one retrievable chunk exists.
            ready_chunk = (
                select(Chunk.id)
                .join(Chunk.document)
                .where(Document.status == "ready", Chunk.user_id == user_id)
                .limit(1)
            )
            if await session.scalar(ready_chunk) is None:
                logger.debug("retrieval: no ready chunks yet; skipping embed")
                return []
        qvec = await embed_query(query)

        async with AsyncSessionLocal() as session:
            # When the HNSW index serves the ordering it filters on user_id
            # after the scan, so a query can return fewer than k rows.
            distance = Chunk.embedding.cosine_distance(qvec)
            stmt = (
                select(
                    Chunk.content,
                    Chunk.chunk_metadata,
                    Chunk.document_id,
                    Chunk.idx,
                    distance.label("distance"),
                )
                .join(Chunk.document)
                .where(Document.status == "ready", Chunk.user_id == user_id)
            )
            if MAX_DISTANCE is not None:
                stmt = stmt.where(distance <= MAX_DISTANCE)
            rows = await session.execute(stmt.order_by(distance).limit(TOP_K))
            results = [
                RetrievedChunk(
                    content=content,
                    filename=(meta or {}).get("filename", "unknown"),
                    distance=float(dist),
                    document_id=document_id,
                    chunk_idx=idx,
                )
                for content, meta, document_id, idx, dist in rows
            ]
            logger.info(
                "retrieval: query_len=%d k=%d cutoff=%s hits=%d distances=%s",
                len(query),
                TOP_K,
                MAX_DISTANCE,
                len(results),
                [round(r.distance, 3) for r in results],
            )
            return results
    except Exception as exc:
        # Type name only at WARNING: an SDK or driver message can quote the
        # query. The detail goes to DEBUG, below production's LOG_LEVEL=INFO.
        logger.warning("retrieval failed: %s", type(exc).__name__)
        logger.debug("retrieval failure detail", exc_info=exc)
        raise RetrievalUnavailable() from None
