import asyncio
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from packages.core import storage
from packages.core.rag.embeddings import embed_documents
from packages.core.rag.errors import PermanentIngestError
from packages.core.rag.extract import extract_text
from packages.core.rag.splitter import split_text
from packages.db import AsyncSessionLocal
from packages.db.models import Chunk, Document

# The states a worker may claim. 'ready' and 'failed' are terminal: the API
# writes 'failed' too (its deadline in routers/documents.py, a publish that
# fails), and the worker never leaves either.
IN_FLIGHT = ("pending", "processing")

# A response of the wrong shape (embeddings.py raises ValueError on a count or
# dimension mismatch) will not change on a retry.
BAD_EMBEDDINGS = "the embedding service returned an unusable response"


async def ingest_document_async(document_id: UUID) -> None:
    """Read a document's raw file from object storage, then chunk -> embed -> store.

    Drives status pending/processing -> ready but never records 'failed' itself —
    it raises, and the calling Celery task owns the terminal status (immediately
    for PermanentIngestError, after retries exhaust otherwise), so the row stays
    'processing' while retries are pending.

    Every status write is conditional on the row still being in flight:
    'processing' is claimed only over pending/processing, and 'ready' is
    written only over 'processing'. A row the API's deadline has failed is
    therefore never resurrected — 'failed' is terminal — and a late attempt
    raises instead of writing. A message redelivered after the work committed
    finds 'ready' and returns.

    Idempotent: chunks commit only together with the conditional 'ready'
    write, whose row lock serializes two attempts — the loser finds 'ready'
    and returns. Invariant: status=ready => one complete chunk set.
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
        # An explicit UPDATE, not an ORM assignment: a retry finds the row
        # already 'processing', and only a statement restarts the deadline
        # clock (updated_at) for the new attempt.
        claimed = await session.execute(
            update(Document)
            .where(Document.id == document_id, Document.status.in_(IN_FLIGHT))
            .values(status="processing", updated_at=func.now())
            .returning(Document.id)
            .execution_options(synchronize_session=False)
        )
        if claimed.first() is None:
            # Only a terminal row misses the claim, so this read is stable.
            status = await session.scalar(
                select(Document.status).where(Document.id == document_id)
            )
            if status == "ready":
                return
            raise PermanentIngestError(
                f"document {document_id} is not in flight (failed or deleted)"
            )
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
        # Parsing is CPU-bound (PDF especially) -> off the loop.
        text = await asyncio.to_thread(extract_text, raw, filename)
        chunks = split_text(text)
        if not chunks:
            raise PermanentIngestError("document produced no chunks after splitting")
        try:
            embeddings = await embed_documents(chunks)
        except ValueError as exc:
            raise PermanentIngestError(BAD_EMBEDDINGS) from exc
        if len(embeddings) != len(chunks):
            raise PermanentIngestError(BAD_EMBEDDINGS)
        # Delete-then-insert atomically with the status write — a re-run can't
        # duplicate chunks. The 'ready' write goes before the chunk inserts so
        # a deleted parent is seen here, not as the inserts' FK violation; the
        # row lock it takes holds a concurrent deadline or delete until commit.
        await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        readied = await session.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == "processing")
            .values(status="ready", error=None, updated_at=func.now())
            .returning(Document.id)
            .execution_options(synchronize_session=False)
        )
        if readied.first() is None:
            # Raising before the commit rolls the chunk delete back with it.
            status = await session.scalar(
                select(Document.status).where(Document.id == document_id)
            )
            if status is None:
                raise PermanentIngestError("document deleted during ingestion")
            if status == "ready":
                # Another attempt finished first; its chunk set stands.
                await session.rollback()
                return
            raise PermanentIngestError("document left processing during ingestion")
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
        # Not transient — fail permanent on attempt 1 instead of re-paying the
        # embed on retries: a constraint violation is schema/code drift.
        try:
            await session.commit()
        except IntegrityError as exc:
            raise PermanentIngestError("chunk insert violated a constraint") from exc


async def mark_document_failed(document_id: UUID, error: str) -> None:
    """Record a terminal 'failed' status + error — the worker's one place to
    write it.

    First terminal write wins: a no-op if the row is gone (deleted mid-ingest),
    already failed (the API deadline's message survives the late attempt it
    stopped) or already ready (a late attempt cannot fail a finished document).
    Receives already-sanitized text — the calling task owns sanitization
    (_public_error); raw detail goes to logs only.
    """
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Document)
            .where(Document.id == document_id, Document.status.in_(IN_FLIGHT))
            .values(status="failed", error=error[:1000])
            .execution_options(synchronize_session=False)
        )
        await session.commit()
