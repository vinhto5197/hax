import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_RAW_URL = os.getenv("DATABASE_URL", "postgresql://hax:hax@localhost:5432/hax")
# SQLAlchemy needs an explicit driver scheme for async; rewrite so .env
# stays driver-agnostic.
DATABASE_URL_ASYNC = _RAW_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL_ASYNC)
# expire_on_commit=False: the default's post-commit lazy reload isn't awaited in
# async and raises MissingGreenlet. Trade-off: objects keep pre-commit values,
# so refresh() explicitly where DB-computed state is needed.
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass
