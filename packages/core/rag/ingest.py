import asyncio
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

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

    Drives status pending/processing -> ready but never records 'failed' itself —
    it raises, and the calling Celery task owns the terminal status (immediately
    for PermanentIngestError, after retries exhaust otherwise), so the row stays
    'processing' while retries are pending.

    Idempotent: the chunk write is delete-then-insert in one transaction, so a
    retry or broker redelivery (acks_late) re-runs cleanly. Invariant:
    status=ready => a complete, current chunk set.
    """
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise PermanentIngestError(f"document {document_id} not found")
        if doc.storage_key is None:
            raise PermanentIngestError(f"document {document_id} has no storage_key")
        storage_key = doc.storage_key
        filename = doc.filename
        user_id = doc.user_id
        doc.status = "processing"
        # Commit now rather than holding one transaction across the whole ingest:
        # frees the pooled connection during the multi-second embed and makes the
        # status visible to the polling UI.
        await session.commit()

        # Blocking boto3 -> off the loop. A missing object is deterministic
        # (S3 is read-after-write consistent) -> permanent.
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
            raise PermanentIngestError("document produced no chunks after splitting")
        embeddings = await embed_documents(chunks)
        # Delete-then-insert atomically with status=ready — a re-run can't
        # duplicate chunks.
        await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        session.add_all(
            Chunk(
                document_id=document_id,
                idx=i,
                content=content,
                chunk_metadata={"filename": filename},
                embedding=embedding,
                user_id=user_id,
            )
            for i, (content, embedding) in enumerate(zip(chunks, embeddings))
        )
        doc.status = "ready"
        doc.error = None
        # A constraint violation here is schema/code drift, not a transient fault
        # — fail permanent on attempt 1 instead of re-paying the embed on retries.
        try:
            await session.commit()
        except IntegrityError as exc:
            raise PermanentIngestError(
                f"chunk insert violated a constraint: {exc}"
            ) from exc


async def mark_document_failed(document_id: UUID, error: str) -> None:
    """Record a terminal 'failed' status + error — the one place it is written.

    No-op if the row is gone (deleted mid-ingest). Raw error text is dev-useful
    while single-tenant; sanitize before M2.5 multi-tenancy.
    """
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is not None:
            doc.status = "failed"
            doc.error = error[:1000]
            await session.commit()
