import asyncio
from uuid import UUID

from sqlalchemy import delete

from packages.core import storage
from packages.core.rag.embeddings import embed_documents
from packages.core.rag.splitter import split_text
from packages.db import AsyncSessionLocal
from packages.db.models import Chunk, Document


class PermanentIngestError(Exception):
    """A deterministic ingestion failure that retrying cannot fix — missing doc,
    missing storage_key, the object absent from storage, non-UTF-8 content, or no
    chunks after splitting.

    The Celery task records the document 'failed' immediately on this, instead of
    retrying. Any OTHER exception (Voyage / S3 / DB I/O) is treated as transient
    and retried with backoff.
    """


async def ingest_document_async(document_id: UUID) -> None:
    """Read a document's raw file from object storage, then chunk -> embed -> store.

    Runs in the Celery worker (slice 2a), off the upload request. Reads the bytes
    by the doc's `storage_key` (set at upload), so it needs no text/filename
    args — everything is reconstructed from the row + storage.

    Drives status pending/processing -> ready. It does **not** record 'failed'
    itself: on any exception it just propagates (the `async with` rolls back the
    open transaction), and the calling task owns the terminal 'failed' status —
    immediately for `PermanentIngestError`, or after retries exhaust for transient
    errors. Leaving the row at 'processing' through retries keeps the polling UI
    waiting instead of prematurely showing 'failed'.

    Idempotent: the chunk write is delete-then-insert in one transaction, so a
    Celery retry or broker redelivery (acks_late) re-runs cleanly without
    duplicating chunks. Invariant: status=ready => a complete, current chunk set.
    """
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise PermanentIngestError(f"document {document_id} not found")
        if doc.storage_key is None:
            raise PermanentIngestError(f"document {document_id} has no storage_key")
        storage_key = doc.storage_key
        filename = doc.filename
        doc.status = "processing"
        # Commit 'processing' immediately rather than holding one transaction across
        # the whole ingest: it returns the pooled connection so the multi-second
        # embed below doesn't pin it, and makes the status visible to the polling UI.
        await session.commit()

        # storage.get is blocking boto3 -> offload so it doesn't block this task's
        # event loop (asyncio.run gives each task its own loop). A missing object
        # is deterministic (S3 is read-after-write consistent) -> permanent; other
        # storage errors propagate natively -> transient.
        try:
            raw = await asyncio.to_thread(storage.get, storage_key)
        except storage.StorageKeyNotFound as exc:
            raise PermanentIngestError(
                f"storage object {storage_key} not found for document {document_id}"
            ) from exc
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PermanentIngestError(
                f"document {document_id} is not valid UTF-8"
            ) from exc
        chunks = split_text(text)
        if not chunks:
            # A 'ready' doc must have >=1 retrievable chunk — otherwise it's
            # silently un-retrievable. Deterministic, so permanent.
            raise PermanentIngestError("document produced no chunks after splitting")
        embeddings = await embed_documents(chunks)
        # Idempotent write: clear any existing chunks for this doc, then insert the
        # fresh set, atomically with status=ready. Safe under retries / redelivery —
        # a re-run can't duplicate chunks.
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


async def mark_document_failed(document_id: UUID, error: str) -> None:
    """Record a terminal 'failed' status + error on a document (best-effort).

    Called by the Celery task for a permanent failure or after transient retries
    exhaust — the one place terminal 'failed' is written. No-op if the row is gone
    (reachable once delete-document exists). The error is truncated; v0 is
    single-tenant so the raw message is dev-useful — sanitize before M2.5
    multi-tenancy (backlogged).
    """
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is not None:
            doc.status = "failed"
            doc.error = error[:1000]
            await session.commit()
