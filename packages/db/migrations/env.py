import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from packages.db.models import *  # noqa: F401, F403

# Import Base and all models so autogenerate sees the tables.
from packages.db.session import MIGRATIONS_DATABASE_URL_ASYNC, Base

config = context.config

# Migrations run as the OWNER role — URL policy lives in packages/db/session.py.
# The URL is passed to SQLAlchemy directly and never stored in the ini config:
# ConfigParser reads "%" as interpolation, and a percent-encoded password
# contains one.

if config.config_file_name is not None:
    # disable_existing_loggers=False: this module also runs in-process from
    # tests/api/conftest.py's test_database fixture (migrating hax_test), by
    # which point app/test loggers already exist. fileConfig's default would
    # silently disable every one of them for the rest of the pytest session.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit the migrations as SQL to stdout instead of running them.

    No Engine and no DBAPI connection — nothing here may read the database.
    """
    context.configure(
        url=MIGRATIONS_DATABASE_URL_ASYNC,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(
        MIGRATIONS_DATABASE_URL_ASYNC, poolclass=pool.NullPool
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
