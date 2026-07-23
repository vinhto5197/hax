"""Document RESPONSE (output) schema — the body FastAPI serializes from ORM rows."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    mime_type: str
    size_bytes: int
    status: str
    error: str | None
    created_at: datetime
    updated_at: datetime
