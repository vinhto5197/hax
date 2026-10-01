"""Raw upload bytes -> plain text, by the file's suffix.

The upload route validated the suffix; this decides the reader. Text formats
are UTF-8; PDF and DOCX are parsed for their text layer only (no OCR), so a
scanned PDF yields nothing and fails with a message the user can act on.
Errors raised here are PermanentIngestError: a file that cannot be read now
will not be readable on retry.
"""

import io

from docx import Document as DocxDocument
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from packages.core.rag.errors import PermanentIngestError


def extract_text(raw: bytes, filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return _pdf(raw)
    if name.endswith(".docx"):
        return _docx(raw)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PermanentIngestError("the file is not valid UTF-8 text") from exc


def _pdf(raw: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
    except (PdfReadError, ValueError, KeyError) as exc:
        raise PermanentIngestError("the PDF could not be read") from exc
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        raise PermanentIngestError(
            "the PDF has no text layer (a scanned PDF?); only text PDFs are supported"
        )
    return text


def _docx(raw: bytes) -> str:
    try:
        doc = DocxDocument(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001 — python-docx raises several types
        raise PermanentIngestError("the Word document could not be read") from exc
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)
