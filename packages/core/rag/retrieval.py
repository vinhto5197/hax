import logging
import os
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


@dataclass
class RetrievedChunk:
    content: str
    filename: str
    distance: float  # cosine distance: 0 = identical direction, 2 = opposite


async def retrieve(query: str, k: int = TOP_K) -> list[RetrievedChunk]:
    """Embed the query and return its k nearest chunks by cosine distance.

    Degrades to [] on ANY fault (no corpus, Voyage down, DB error) so chat never
    hard-fails on retrieval; the traceback is logged so real bugs stay visible.
    Only chunks of status='ready' documents are searched — in-flight or failed
    ingests never leak partial chunks (delete-then-insert makes 'ready' imply a
    complete chunk set). No user filter yet (M2.5). RAG_MAX_DISTANCE, if set,
    drops chunks farther than the cutoff.
    """
    try:
        async with AsyncSessionLocal() as session:
            # Skip the paid embed unless at least one retrievable chunk exists.
            ready_chunk = (
                select(Chunk.id)
                .join(Chunk.document)
                .where(Document.status == "ready")
                .limit(1)
            )
            if await session.scalar(ready_chunk) is None:
                logger.debug("retrieval: no ready chunks yet; skipping embed")
                return []
            qvec = await embed_query(query)

            # Lazy SQL expression (embedding <=> qvec), evaluated per row by
            # Postgres; the HNSW index serves the nearest-k ordering.
            distance = Chunk.embedding.cosine_distance(qvec)
            stmt = (
                select(Chunk.content, Chunk.chunk_metadata, distance.label("distance"))
                .join(Chunk.document)
                .where(Document.status == "ready")
            )
            if MAX_DISTANCE is not None:
                stmt = stmt.where(distance <= MAX_DISTANCE)
            rows = await session.execute(stmt.order_by(distance).limit(k))
            results = [
                RetrievedChunk(
                    content=content,
                    filename=(meta or {}).get("filename", "unknown"),
                    distance=float(dist),
                )
                for content, meta, dist in rows
            ]
            # Debug observability: what came back and how near (ascending).
            logger.info(
                "retrieval: query_len=%d k=%d cutoff=%s hits=%d distances=%s",
                len(query),
                k,
                MAX_DISTANCE,
                len(results),
                [round(r.distance, 3) for r in results],
            )
            return results
    except Exception:
        logger.warning("retrieval failed; serving chat without RAG", exc_info=True)
        return []
