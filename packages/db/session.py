import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


def to_async_url(url: str) -> str:
    # SQLAlchemy needs an explicit driver scheme for async; rewrite here so
    # .env stays driver-agnostic. The ONLY place this rewrite may live.
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


_RAW_URL = os.getenv("DATABASE_URL", "postgresql://hax:hax@localhost:5432/hax")
DATABASE_URL_ASYNC = to_async_url(_RAW_URL)

# Owner-role URL for Alembic/admin tooling (DDL needs ownership; the runtime
# role deliberately can't). Falls back to the app URL so a fresh clone
# without the split still migrates — single-role.
MIGRATIONS_DATABASE_URL_ASYNC = to_async_url(
    os.getenv("MIGRATIONS_DATABASE_URL") or _RAW_URL
)

engine = create_async_engine(DATABASE_URL_ASYNC)
# expire_on_commit=False: the default's post-commit lazy reload isn't awaited in
# async and raises MissingGreenlet. Trade-off: objects keep pre-commit values,
# so refresh() explicitly where DB-computed state is needed.
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass
