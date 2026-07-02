import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_session
from apps.worker.tasks import ingest_document
from packages.core import storage
from packages.core.schemas.document import DocumentOut
from packages.db.models import Document

router = APIRouter(prefix="/documents", tags=["documents"])

# Cap uploads small: the whole file is read into memory here (and again on the
# worker). Large files (streaming/multipart upload) are a v1 concern; a general
# request-body limit is an M5 item.
MAX_BYTES = 256 * 1024
# Allowed suffixes -> the mime we persist. We derive mime from the validated
# suffix rather than trusting the client's content_type.
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
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    filename = file.filename or "upload"
    # First allowed extension the filename ends with, else None. We keep the
    # matched suffix (not just a bool) to look up its trusted mime below.
    suffix = next((s for s in SUFFIX_MIME if filename.lower().endswith(s)), None)
    if suffix is None:
        raise HTTPException(
            status_code=400, detail="only .txt and .md files are supported"
        )

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"file exceeds {MAX_BYTES} bytes")
    if not content.strip():
        raise HTTPException(status_code=400, detail="file is empty")
    try:
        # Validate UTF-8 at the edge for a fast 400; the worker re-decodes the
        # bytes from storage, so we don't keep the decoded text here.
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

    # Write the raw bytes to object storage (S3/MinIO) BEFORE committing, so a
    # 'pending' row never exists without its file — if the put fails, the flushed
    # row rolls back. storage.put is blocking (boto3) → offload from the event
    # loop. The id-scoped key keeps each upload's object isolated.
    storage_key = f"documents/{doc.id}/{filename}"
    await asyncio.to_thread(storage.put, storage_key, content, doc.mime_type)
    doc.storage_key = storage_key
    await session.commit()
    await session.refresh(doc)

    # Hand ingestion to the Celery worker (durable in the Redis broker, retried,
    # off the request) and return immediately at 'pending'. The worker reads the
    # raw bytes back from storage by storage_key, so the task needs only the id —
    # passed as a str because the JSON broker can't carry a UUID. The UI polls
    # GET /api/documents for the status flip (pending -> processing -> ready|failed).
    ingest_document.delay(str(doc.id))
    return DocumentOut.model_validate(doc)
