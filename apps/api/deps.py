from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db import AsyncSessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: request-scoped async DB session (short CRUD routes).

    The chat route deliberately does NOT use this — a request-scoped session
    would pin a pooled connection for the entire SSE stream, so chat_service
    opens its own short-lived sessions at the start and end of a turn instead.
    """
    async with AsyncSessionLocal() as session:
        yield session
