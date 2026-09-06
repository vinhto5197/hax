"""Per-request/per-task identity for the DB layer.

Cross-module contract: apps SET this ContextVar (apps/api/auth.py's
current_user for requests; apps/worker/tasks.py's task body for jobs) and the
engine's begin listener (session.py) announces it to Postgres as
SET LOCAL app.current_user_id on EVERY transaction — no callsite may issue its
own SET LOCAL. Unset => nothing announced => RLS policies compare against NULL
=> zero rows (fail-closed by construction).
"""

import uuid
from contextvars import ContextVar

current_user_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_user_id", default=None
)
