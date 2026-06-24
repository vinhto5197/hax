from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db import AsyncSessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a request-scoped async DB session.

    The session opens before the route runs and closes after the response is
    sent — which makes it a good fit for the short conversations CRUD routes.

    The streaming chat routes deliberately do NOT use this and manage their own
    short-lived sessions instead (see apps/api/chat_service.py). A request-scoped
    session would stay open for the *entire* SSE stream — many seconds of holding
    a pooled connection idle while no DB work happens (and risking it going stale
    mid-stream). Chat instead grabs a connection only for the two short bursts at
    the start and end of a turn, and holds nothing during the long stream between.
    """
    async with AsyncSessionLocal() as session:
        yield session
