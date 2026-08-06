import asyncio
import logging
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_session
from apps.worker.tasks import ingest_document
from packages.core import storage
from packages.core.schemas.document import DocumentOut
from packages.db.models import Document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# Whole file is buffered in memory; streaming uploads are out of v0 scope.
MAX_BYTES = 256 * 1024
# Mime derived from the validated suffix — the client's content_type is untrusted.
SUFFIX_MIME = {".txt": "text/plain", ".md": "text/markdown"}


@router.get("")
async def list_documents(
    session: AsyncSession = Depends(get_session),
) -> list[DocumentOut]:
    # Most-recent first. No auth filter yet — returns every document.
    result = await session.scalars(
        select(Document).order_by(Document.created_at.desc())
    )
    return [DocumentOut.model_validate(d) for d in result]


@router.post("")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    filename = file.filename or "upload"
    suffix = next((s for s in SUFFIX_MIME if filename.lower().endswith(s)), None)
    if suffix is None:
        raise HTTPException(
            status_code=400, detail="only .txt and .md files are supported"
        )

    # Reject on the declared length BEFORE buffering anything — an honest large
    # client costs zero reads. (A lying/absent Content-Length is caught below.)
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"file exceeds {MAX_BYTES} bytes")

    # Bounded read caps RAM at MAX_BYTES+1 even when the header lies; the deeper
    # multipart disk-spool is the reverse proxy's client_max_body_size job (M3).
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"file exceeds {MAX_BYTES} bytes")
    if not content.strip():
        raise HTTPException(status_code=400, detail="file is empty")
    try:
        # Validate UTF-8 at the edge (fast 400); the worker re-decodes from storage.
        content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="file must be UTF-8 text")

    doc = Document(
        filename=filename,
        mime_type=SUFFIX_MIME[suffix],
        size_bytes=len(content),
        status="pending",
    )
    session.add(doc)
    await session.flush()  # populate the server-default id so we can key the file

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
    try:
        ingest_document.delay(str(doc.id))
    except Exception:
        # The row is already committed, so a broker outage here would strand the
        # doc at 'pending' with no task enqueued. Mark it 'failed' so 'pending'
        # always means a task is really queued.
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
) -> Response:
    # No auth filter yet — M2.5 scopes deletes by user_id.
    doc = await session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    # DB row first (source of truth; chunks go via ON DELETE CASCADE), storage
    # second and best-effort: a storage failure after the commit only leaks an
    # orphaned object, so log it rather than 500 an already-completed delete.
    # storage_key is None for docs ingested before object storage existed.
    storage_key = doc.storage_key
    await session.delete(doc)
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
