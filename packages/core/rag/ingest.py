import logging
from uuid import UUID

from packages.core.rag.embeddings import embed_documents
from packages.core.rag.splitter import split_text
from packages.db import AsyncSessionLocal
from packages.db.models import Chunk, Document

logger = logging.getLogger(__name__)


async def ingest_document(document_id: UUID, text: str, filename: str) -> Document:
    """Chunk -> embed -> store the chunks for an already-created document.

    Drives the document's status: processing -> ready, or -> failed (with the
    error recorded) on any exception. The failure recovery is itself guarded so a
    secondary DB error can't leave the row stuck in 'processing' or 500 the
    caller. Self-contained (own session) so M2 slice 2 can call it from a Celery
    task unchanged; slice 1 awaits it inline in the upload request.
    """
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise ValueError(f"document {document_id} not found")
        doc.status = "processing"
        # Commit 'processing' now rather than holding one transaction across the
        # whole ingest. Independent of UI visibility (slice-1 uploads ingest
        # synchronously, so the client only ever sees the final status): commit
        # returns the pooled connection so the multi-second embed below doesn't
        # pin it, and leaves a durable 'processing' row a crashed run can be
        # recovered from. Concurrent-reader visibility starts mattering in
        # slice 2 (Celery + polling).
        await session.commit()

        try:
            chunks = split_text(text)
            if not chunks:
                # A 'ready' doc must have >=1 retrievable chunk — otherwise it's
                # silently un-retrievable. Fail it instead.
                raise ValueError("document produced no chunks after splitting")
            embeddings = await embed_documents(chunks)
            # NOT idempotent: re-ingesting appends chunks without clearing prior
            # ones. Safe in slice 1 (called once inline per upload), but when
            # Celery retries land (slice 2) a retry after partial success would
            # duplicate chunks — delete existing `document_id` chunks here first,
            # or upsert, before this runs more than once.
            session.add_all(
                Chunk(
                    document_id=document_id,
                    idx=i,
                    content=content,
                    chunk_metadata={"filename": filename},
                    embedding=embedding,
                )
                for i, (content, embedding) in enumerate(zip(chunks, embeddings))
            )
            doc.status = "ready"
            doc.error = None
            await session.commit()
        except Exception as exc:
            logger.exception("ingestion failed for document %s", document_id)
            # Record the failure best-effort; never re-raise from the handler, so
            # a secondary failure can't leave the row 'processing' or 500 the
            # upload. (v0 is single-tenant; the raw error is dev-useful. Sanitize
            # before M2.5 multi-tenancy — backlogged.)
            try:
                # If the failure came from the commit above, Postgres aborted the
                # transaction and the session is unusable until rolled back — reset
                # it so the queries below can run. (No-op if the failure was
                # upstream, e.g. the embedding call, where no txn was open.)
                await session.rollback()
                # Re-fetch on the now-clean session (rollback expired the old doc
                # object). Returns None if the row was deleted meanwhile —
                # reachable once delete-document exists (slice 2); guarded here.
                doc = await session.get(Document, document_id)
                if doc is not None:
                    doc.status = "failed"
                    doc.error = str(exc)[:1000]
                    await session.commit()
            except Exception:
                logger.exception(
                    "failed to record 'failed' status for document %s", document_id
                )

        # Best-effort refresh so the returned doc reflects the committed
        # status/error. Guarded: the session may be degraded in a failure path,
        # and this handler must never raise — a slightly stale doc beats a 500.
        if doc is not None:
            try:
                await session.refresh(doc)
            except Exception:
                logger.exception("failed to refresh document %s", document_id)
        return doc
