from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db import AsyncSessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a request-scoped async DB session.

    The session opens before the route runs and closes after the response is
    sent. Used by the conversations CRUD routes. The streaming chat routes
    manage their own sessions (see apps/api/chat_service.py) because their DB
    work outlives the request handler — it happens inside the SSE generator.
    """
    async with AsyncSessionLocal() as session:
        yield session
