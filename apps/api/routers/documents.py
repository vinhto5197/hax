import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import anyio
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import CurrentUser, current_user
from apps.api.demo import refuse_visitor
from apps.api.deps import get_session
from apps.api.enqueue import publish
from apps.api.redis_client import get_redis
from apps.worker.tasks import ingest_document
from packages.core import storage
from packages.core.auth import rate_limit
from packages.core.schemas.document import DocumentOut
from packages.db.repos import documents as documents_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# Mime derived from the validated suffix — the client's content_type is untrusted.
SUFFIX_MIME = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
TEXT_SUFFIXES = {".txt", ".md"}
# Whole file is buffered in memory; streaming uploads are out of v0 scope.
# Text is dense, so its cap is smaller; binary formats carry layout overhead.
TEXT_MAX_BYTES = 256 * 1024
# An ingest still pending or processing this long has lost its worker: one
# attempt is capped at 300 s and a deploy waits up to that for in-flight work.
# A deadline that fires on a live attempt costs a flicker, not the document:
# the attempt still writes 'ready' over it when it finishes.
STUCK_AFTER = timedelta(minutes=10)
STUCK_ERROR = "processing did not finish; upload the file again"
BINARY_MAX_BYTES = 5 * 1024 * 1024
# Per-user caps on accepted uploads (fixed windows in Redis); every upload
# costs storage, a worker slot and embedding spend.
UPLOADS_PER_HOUR = 5
UPLOADS_PER_DAY = 15


@router.get("")
async def list_documents(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> list[DocumentOut]:
    # The deadline on in-flight documents is applied here, on read, because
    # the one case that strands a row — the worker killed mid-task — leaves
    # no process to write the terminal status, and the panel reads this list
    # whenever it shows the row.
    stale = await documents_repo.fail_stale(
        session, user.id, datetime.now(UTC) - STUCK_AFTER, STUCK_ERROR
    )
    if stale:
        await session.commit()
    documents = await documents_repo.list_for_user(session, user.id)
    return [DocumentOut.model_validate(d) for d in documents]


@router.post(
    "",
    responses={
        403: {"description": "demo_limit: sign up to upload"},
        429: {"description": "upload limit reached"},
    },
)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> DocumentOut:
    refuse_visitor(user)
    filename = file.filename or "upload"
    suffix = next((s for s in SUFFIX_MIME if filename.lower().endswith(s)), None)
    if suffix is None:
        raise HTTPException(
            status_code=400, detail="supported files: .txt, .md, .pdf, .docx"
        )
    max_bytes = TEXT_MAX_BYTES if suffix in TEXT_SUFFIXES else BINARY_MAX_BYTES

    # By the time this runs the multipart body has already been received and
    # spooled (Starlette parses the form before dependencies resolve); the
    # proxy's request-body cap (Caddyfile) is what refuses an oversized body
    # early. The declared length is a cheap first answer for an honest client.
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"file exceeds {max_bytes // 1024} KB"
        )

    # Bounded read caps RAM at max_bytes+1 even when the header lies.
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"file exceeds {max_bytes // 1024} KB"
        )
    if not content.strip():
        raise HTTPException(status_code=400, detail="file is empty")
    # Content is not inspected here: the worker parses the bytes it fetches
    # back from storage, and anything unreadable (bad UTF-8, a text-less PDF)
    # marks the document failed with a reason the panel shows.

    # Only an accepted upload spends a slot: every rejection above returns
    # before this line. Keyed on the user id so password and Google accounts
    # are bounded alike; a visitor never reaches here (refuse_visitor runs
    # first). A storage failure after the hit still spends one, like a demo
    # turn the model then fails. Fail-open on Redis is the limiter's contract.
    ident = str(user.id)
    if not await rate_limit.hit(
        get_redis(), "upload_hour", ident, limit=UPLOADS_PER_HOUR, window_s=3600
    ):
        raise HTTPException(429, detail="upload limit reached; try again later")
    # The hour slot spent just above is harmless when the day refuses: the
    # day is exhausted either way.
    if not await rate_limit.hit(
        get_redis(), "upload_day", ident, limit=UPLOADS_PER_DAY, window_s=86400
    ):
        raise HTTPException(429, detail="upload limit reached; try again later")

    doc = await documents_repo.create(
        session,
        user.id,
        filename=filename,
        mime_type=SUFFIX_MIME[suffix],
        size_bytes=len(content),
    )

    # Store the file BEFORE committing, so a 'pending' row never exists without
    # its bytes (a failed put rolls the flushed row back). Blocking boto3 →
    # off the event loop.
    storage_key = f"documents/{doc.id}/{filename}"
    await asyncio.to_thread(storage.put, storage_key, content, doc.mime_type)
    doc.storage_key = storage_key
    await session.commit()
    await session.refresh(doc)

    # Enqueue ingestion (Celery) and return at 'pending'; the UI polls for the
    # status flip. The id goes as a str — the JSON broker can't carry a UUID.
    # Shielded: a client disconnect during a slow publish must not cancel the
    # handler between the commit and the mark-failed below.
    with anyio.CancelScope(shield=True):
        try:
            await publish(ingest_document, str(doc.id), str(user.id))
        except Exception:
            # The row is already committed, so a broker outage here would
            # strand the doc at 'pending' with no task enqueued. Mark it
            # 'failed' so 'pending' always means a task is really queued.
            logger.exception("failed to enqueue ingestion for document %s", doc.id)
            doc.status = "failed"
            doc.error = "could not start ingestion (task queue unavailable)"
            await session.commit()
            await session.refresh(doc)
    return DocumentOut.model_validate(doc)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> Response:
    doc = await documents_repo.delete_owned(session, user.id, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    # DB row first (source of truth), storage second and best-effort: a storage
    # failure after commit only leaks an orphaned object — log, don't 500.
    # storage_key is None when the put never succeeded (the row is flushed first).
    storage_key = doc.storage_key
    await session.commit()

    if storage_key:
        try:
            await asyncio.to_thread(storage.delete, storage_key)
        except Exception:
            logger.warning(
                "deleted document %s but failed to remove its storage object %s "
                "(orphaned; safe to sweep later)",
                document_id,
                storage_key,
                exc_info=True,
            )

    return Response(status_code=204)
