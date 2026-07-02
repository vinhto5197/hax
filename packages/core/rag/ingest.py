import asyncio
import logging
from uuid import UUID

from sqlalchemy import delete

from packages.core import storage
from packages.core.rag.embeddings import embed_documents
from packages.core.rag.splitter import split_text
from packages.db import AsyncSessionLocal
from packages.db.models import Chunk, Document

logger = logging.getLogger(__name__)


async def ingest_document_async(document_id: UUID) -> None:
    """Read a document's raw file from object storage, then chunk -> embed -> store.

    Runs in the Celery worker (slice 2a), off the upload request. Reads the bytes
    by the doc's `storage_key` (set at upload), so it needs no text/filename
    args — everything is reconstructed from the row + storage. Drives status
    processing -> ready, or -> failed (error recorded) on any exception.

    Idempotent: the chunk write is delete-then-insert in one transaction, so a
    Celery retry or broker redelivery (acks_late) re-runs cleanly without
    duplicating chunks. Invariant: status=ready => a complete, current chunk set.

    Re-raises on failure (after recording 'failed') so the calling task can act on
    it — step 3b adds transient-vs-permanent retry on top.
    """
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise ValueError(f"document {document_id} not found")
        if doc.storage_key is None:
            raise ValueError(f"document {document_id} has no storage_key")
        storage_key = doc.storage_key
        filename = doc.filename
        doc.status = "processing"
        # Commit 'processing' immediately rather than holding one transaction
        # across the whole ingest: it returns the pooled connection so the
        # multi-second embed below doesn't pin it, makes the status visible to the
        # polling UI, and leaves a durable marker a crashed run can be recovered
        # from.
        await session.commit()

        try:
            # storage.get is blocking boto3 -> offload so it doesn't block this
            # task's event loop (asyncio.run gives each task its own loop).
            raw = await asyncio.to_thread(storage.get, storage_key)
            text = raw.decode("utf-8")
            chunks = split_text(text)
            if not chunks:
                # A 'ready' doc must have >=1 retrievable chunk — otherwise it's
                # silently un-retrievable. Fail it instead.
                raise ValueError("document produced no chunks after splitting")
            embeddings = await embed_documents(chunks)
            # Idempotent write: clear any existing chunks for this doc, then insert
            # the fresh set, atomically with status=ready. Safe under retries /
            # redelivery — a re-run can't duplicate chunks.
            await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
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
            # Record 'failed' best-effort, then re-raise. The recovery is itself
            # guarded so a secondary DB error can't mask the original failure.
            # (v0 is single-tenant; the raw error is dev-useful. Sanitize before
            # M2.5 multi-tenancy — backlogged.)
            try:
                # If the failure came from the commit, Postgres aborted the txn and
                # the session is unusable until rolled back. (No-op otherwise, e.g.
                # an embedding failure where no txn was open.)
                await session.rollback()
                # Re-fetch on the now-clean session (rollback expired the old doc).
                # None if the row was deleted meanwhile (reachable once
                # delete-document exists) — guarded here.
                doc = await session.get(Document, document_id)
                if doc is not None:
                    doc.status = "failed"
                    doc.error = str(exc)[:1000]
                    await session.commit()
            except Exception:
                logger.exception(
                    "failed to record 'failed' status for document %s", document_id
                )
            raise
