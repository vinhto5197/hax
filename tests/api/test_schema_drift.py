"""The migrated schema matches the models in what alembic's compare_metadata
compares: tables, columns, column types, nullability, indexes, unique
constraints and foreign keys. A model change of that kind without its
migration (or the reverse) fails here, not at deploy. It does not compare
CHECK constraints, server defaults, RLS policies or grants: drift in those
passes this test."""

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
