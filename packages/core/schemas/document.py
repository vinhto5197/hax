"""Document RESPONSE (output) schema — the body FastAPI serializes from ORM rows."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from packages.db.models.document import DocumentStatus


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    error: str | None
    created_at: datetime
    updated_at: datetime
