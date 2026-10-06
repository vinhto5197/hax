"""The migration ledger: the app role reads it and can never write it."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from packages.db import engine as app_engine


async def test_app_role_cannot_write_alembic_version():
    async with app_engine.connect() as conn:
        head = await conn.execute(text("SELECT version_num FROM alembic_version"))
        assert head.one()
        with pytest.raises(ProgrammingError, match="permission denied"):
            await conn.execute(
                text("UPDATE alembic_version SET version_num = version_num")
            )
