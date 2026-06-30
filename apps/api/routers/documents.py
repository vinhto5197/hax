import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_session
from packages.core import storage
from packages.core.rag.ingest import ingest_document
from packages.core.schemas.document import DocumentOut
from packages.db.models import Document

router = APIRouter(prefix="/documents", tags=["documents"])

# Slice 1 caps uploads small because ingestion runs synchronously in the request
# (the whole file is read into memory). Raised once Celery owns ingestion
# (M2 slice 2). A general request-body limit is an M5 item.
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
        text = content.decode("utf-8")
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

    # Slice 1: ingest inline (chunk -> embed -> store), driving status to
    # ready|failed before responding. Slice 2 moves this onto Celery.
    #
    # SIGNPOST for the Celery slice: "just await it" is async, not a background
    # job. Async takes the work off the EVENT LOOP (other requests keep being
    # served while this awaits) — but it's still inside THIS request: the
    # uploader waits the full chunk+embed+store time, which on a large file can
    # exceed the load balancer's request timeout (~60s) and is lost entirely on a
    # crash or a client disconnect (hard reload / closed tab). Celery takes it
    # off the REQUEST: return 'pending' immediately, run ingestion in a worker
    # process (durable in the Redis broker, retried with backoff), UI polls for
    # status. Bonus: a worker process has its own GIL, so any CPU-bound step
    # added later (PDF parse, OCR) gets real parallelism a thread couldn't.
    # ingest_document is already self-contained (own session) for exactly this.
    await ingest_document(doc.id, text, filename)
    await session.refresh(doc)  # pick up the status/error written by ingestion
    return DocumentOut.model_validate(doc)
