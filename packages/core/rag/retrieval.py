import logging
from dataclasses import dataclass

from sqlalchemy import select

from packages.core.rag.config import TOP_K
from packages.core.rag.embeddings import embed_query
from packages.db import AsyncSessionLocal
from packages.db.models import Chunk, Document

logger = logging.getLogger(__name__)


# Named return type for retrieve(): callers use chunk.filename / chunk.content
# (see prompt.py) instead of unpacking opaque tuples. `distance` is captured for
# slice-2 tuning (log it to pick k / a max-distance cutoff) and future citations
# — it is NOT rendered into the prompt yet.
@dataclass
class RetrievedChunk:
    content: str
    filename: str
    distance: float  # cosine distance: 0 = identical direction, 2 = opposite


async def retrieve(query: str, k: int = TOP_K) -> list[RetrievedChunk]:
    """Embed the query and return its k nearest chunks by cosine distance.

    Degrades to [] on ANY fault so chat never hard-fails on the retrieval path —
    the whole body (corpus check, embedding, vector search, materialization) is
    guarded. Causes: no chunks ingested yet (the embed call is skipped to avoid a
    paid request before any data exists); VOYAGE_API_KEY unset / Voyage down;
    a DB/search error. The traceback is logged (exc_info) so a real bug — e.g. a
    dimension mismatch from embeddings._check_dim — is visible, not silent.

    Only chunks from documents with status='ready' are searched, so a doc that is
    pending / processing / re-ingesting / failed never leaks partial or stale
    chunks into an answer (the atomic delete-then-insert write means 'ready' always
    implies a complete, current chunk set). No user filter yet — added in M2.5
    (`WHERE user_id = :uid`).
    """
    try:
        async with AsyncSessionLocal() as session:
            # Skip the (paid) embed unless there's at least one retrievable chunk —
            # i.e. one belonging to a 'ready' document.
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

            # A lazy SQL expression (embedding <=> qvec), not a computed value —
            # Postgres evaluates it per row at execute time. Reused in both the
            # select (.label names the result column "distance") and the order_by
            # (the HNSW index serves the nearest-k ordering).
            distance = Chunk.embedding.cosine_distance(qvec)
            rows = await session.execute(
                select(Chunk.content, Chunk.chunk_metadata, distance.label("distance"))
                .join(Chunk.document)
                .where(Document.status == "ready")
                .order_by(distance)
                .limit(k)
            )
            results = [
                RetrievedChunk(
                    content=content,
                    filename=(meta or {}).get("filename", "unknown"),
                    distance=float(dist),
                )
                for content, meta, dist in rows
            ]
            # Debug observability — NOT a tuning oracle (picking a cutoff needs a
            # labeled eval set, M5). Logs what came back and how near, so a bad
            # answer can be diagnosed: retrieved junk? nothing? good chunk ranked
            # low? Distances are ascending (nearest first).
            logger.info(
                "retrieval: query_len=%d k=%d hits=%d distances=%s",
                len(query),
                k,
                len(results),
                [round(r.distance, 3) for r in results],
            )
            return results
    except Exception:
        logger.warning("retrieval failed; serving chat without RAG", exc_info=True)
        return []
