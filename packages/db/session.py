import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_RAW_URL = os.getenv("DATABASE_URL", "postgresql://hax:hax@localhost:5432/hax")
# SQLAlchemy needs an explicit driver scheme for async; rewrite so .env
# stays driver-agnostic.
DATABASE_URL_ASYNC = _RAW_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL_ASYNC)
# expire_on_commit=False: the default (True) expires every attribute on commit so
# the next read re-SELECTs fresh data — but in async that lazy reload isn't
# awaited and raises MissingGreenlet, and it adds needless SELECTs when we just
# want to serialize the row we committed. Trade-off: objects keep their pre-commit
# values, so we refresh() explicitly when we need DB-computed state (see
# upload_document).
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass
