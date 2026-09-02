import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from packages.db.models import *  # noqa: F401, F403

# Import Base and all models so autogenerate sees the tables.
from packages.db.session import MIGRATIONS_DATABASE_URL_ASYNC, Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Migrations run as the OWNER role — URL policy lives in packages/db/session.py.
config.set_main_option("sqlalchemy.url", MIGRATIONS_DATABASE_URL_ASYNC)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    # disable_existing_loggers=False: this module also runs in-process from
    # tests/api/conftest.py's test_database fixture (migrating hax_test), by
    # which point app/test loggers already exist. fileConfig's default would
    # silently disable every one of them for the rest of the pytest session.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
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
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
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
