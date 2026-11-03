"""Document status and message role are one closed set, end to end.

The Literal in the model file is the single source. These tests pin the two
places that would otherwise drift from it silently: the OpenAPI spec (which
the generated TypeScript is built from) and the live CHECK constraints, which
Alembic autogenerate never compares — a Literal edited without a hand-written
migration fails here and nowhere else.
"""

import re

from sqlalchemy import String, text

from apps.api.main import app
from packages.db.models.document import DOCUMENT_STATUSES, Document
from packages.db.models.message import MESSAGE_ROLES, Message

# Postgres stores `status IN ('a', 'b')` as
# `((status)::text = ANY ((ARRAY['a'::character varying, ...])::text[]))`,
# so the values are read as the single-quoted literals, never by parsing IN.
_QUOTED = re.compile(r"'([^']*)'")


async def _check_values(admin_engine, constraint: str) -> set[str]:
    async with admin_engine.connect() as conn:
        definition = await conn.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = :name"
            ),
            {"name": constraint},
        )
    assert definition is not None, f"{constraint} is missing from the schema"
    return set(_QUOTED.findall(definition))


def _schema_property(schema: str, prop: str) -> dict:
    return app.openapi()["components"]["schemas"][schema]["properties"][prop]


def test_openapi_lists_document_statuses():
    status = _schema_property("DocumentOut", "status")
    assert status["type"] == "string"
    assert status["enum"] == list(DOCUMENT_STATUSES)
    assert status["enum"] == ["pending", "processing", "ready", "failed"]


def test_openapi_lists_message_roles():
    role = _schema_property("MessageOut", "role")
    assert role["type"] == "string"
    assert role["enum"] == list(MESSAGE_ROLES)
    assert role["enum"] == ["user", "assistant"]


async def test_document_status_check_matches_literal(admin_engine):
    values = await _check_values(admin_engine, "documents_status_check")
    assert values == set(DOCUMENT_STATUSES)


async def test_message_role_check_matches_literal(admin_engine):
    values = await _check_values(admin_engine, "messages_role_check")
    assert values == set(MESSAGE_ROLES)


def test_closed_set_columns_stay_unbounded_strings():
    # Exact type, never isinstance: sqlalchemy.Enum subclasses String, so an
    # isinstance check would pass the bare-Literal regression this catches.
    for column in (Document.__table__.c.status, Message.__table__.c.role):
        assert type(column.type) is String, f"{column}: {column.type!r}"
        assert column.type.length is None, f"{column}: {column.type!r}"
