"""Conversation RESPONSE (output) schemas — bodies FastAPI serializes from ORM rows."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MessageOut(BaseModel):
    # from_attributes lets us build these straight from ORM rows.
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]
