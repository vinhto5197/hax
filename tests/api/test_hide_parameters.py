"""Engine-level parameter hiding: SQLAlchemy's
StatementError.__str__ appends "[parameters: …]" by default, and for the
chunk insert those parameters are raw user document text. hide_parameters is
an ENGINE option applied when the engine itself wraps a DBAPI error, so this
is exercised through packages.db.engine on a real failing statement — a
manually constructed exception (sqlalchemy.exc.OperationalError(...)) would
not honor the flag and would give a false negative.
"""

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from packages.db import engine


async def test_dbapi_error_does_not_leak_bound_parameters():
    async with engine.connect() as conn:
        try:
            # uid is not a valid uuid -> DBAPIError; title is the leak-bait
            # bound parameter that hide_parameters must keep out of str(exc).
            await conn.execute(
                text(
                    "INSERT INTO conversations (user_id, title) VALUES (:uid, :title)"
                ),
                {"uid": "not-a-uuid", "title": "LEAKED-PARAM"},
            )
        except DBAPIError as exc:
            assert "LEAKED-PARAM" not in str(exc)
        else:
            raise AssertionError("expected the invalid uuid to raise DBAPIError")
