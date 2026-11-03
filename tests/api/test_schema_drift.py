"""The migrated schema is what the models declare: a model change without its
migration (or the reverse) fails here, not at deploy."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

import packages.db.models  # noqa: F401  (registers every table on Base)
from packages.db.session import Base


async def test_models_match_the_migrated_schema(admin_engine):
    def diff(sync_conn):
        context = MigrationContext.configure(sync_conn)
        return compare_metadata(context, Base.metadata)

    async with admin_engine.connect() as conn:
        changes = await conn.run_sync(diff)
    assert changes == []
