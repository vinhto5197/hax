"""Chat REQUEST (input) schema — the body POST /api/chat parses."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, StringConstraints

ModelId = Literal["claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-8"]


class ChatRequest(BaseModel):
    # Reject empty/whitespace-only prompts at the edge (422): the Anthropic API
    # 400s on empty content, and a persisted empty turn would be replayed by
    # load_history into every later request — permanently breaking the
    # conversation. strip_whitespace matters: whitespace-only also 400s.
    # max_length caps the unbounded body that otherwise feeds straight to the
    # paid LLM and an unbounded TEXT column (~20k chars ≈ 5k tokens, well under
    # the model's context window; large data belongs in a document upload, not
    # a chat turn).
    prompt: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)
    ]
    # None on the first turn of a new chat — the server lazily creates a
    # conversation and returns its id in the SSE prelude.
    conversation_id: UUID | None = None
    # Optional per-request model override. The allowed ids are exactly the
    # choices the UI offers (MODEL_OPTIONS in
    # apps/web/components/chat/ModelSelect.tsx); anything else is a 422 before
    # any model is called. None -> the server's DEFAULT_MODEL (env LLM_MODEL);
    # the web sends null, never "", for Default.
    model: ModelId | None = None
    # The user message's id, chosen by the client so it can later ask whether
    # this send reached the server. An id already stored is a duplicate send
    # (409). None -> the database assigns one.
    message_id: UUID | None = None
