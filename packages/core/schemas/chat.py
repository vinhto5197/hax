from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, StringConstraints


class ChatRequest(BaseModel):
    # Reject empty/whitespace-only prompts at the edge (422): the Anthropic API
    # 400s on empty content, and a persisted empty turn would be replayed by
    # load_history into every later request — permanently breaking the
    # conversation. strip_whitespace matters: whitespace-only also 400s.
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    # None on the first turn of a new chat — the server lazily creates a
    # conversation and returns its id in the SSE prelude.
    conversation_id: UUID | None = None
