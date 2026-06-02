from uuid import UUID

from pydantic import BaseModel


class ChatRequest(BaseModel):
    prompt: str
    # None on the first turn of a new chat — the server lazily creates a
    # conversation and returns its id in the SSE prelude.
    conversation_id: UUID | None = None
