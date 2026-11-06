"""Every table in the public schema is under row-level security, enabled and
FORCEd, with at least one policy, unless EXEMPT names it with a reason — read
from the catalog, so a new table that ships without RLS fails here rather
than in a review, whether it carries its own user_id or is owned through a
parent (as messages is, through its conversation).

Adding a table to EXEMPT is a decision for ADR 0012, not for this file."""

from sqlalchemy import text

EXEMPT = {
    # Alembic's revision ledger: no user data, read by migrations as the owner.
    "alembic_version": "migration ledger, holds no user rows",
    # ADR 0012's standing decision: both serve pre-session flows (oauth-upsert,
    # email-link verification) and are bounded by their one repo module each,
    # keyed by provider identity or a hashed token, never a caller's user id.
    "accounts": "pre-session OAuth lookups; ADR 0012",
    "email_tokens": "pre-session email-link lookups; ADR 0012",
    # The identity table itself: credential checks, OAuth upsert and the
    # per-request revocation check read it before any identity is announced.
    "users": "read before an identity exists to announce",
}


async def _public_tables(admin_engine) -> dict[str, tuple[bool, bool, int]]:
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,"
                "  (SELECT count(*) FROM pg_policies p"
                "    WHERE p.schemaname = 'public' AND p.tablename = c.relname)"
                " FROM pg_class c"
                " JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
            )
        )
        return {row[0]: tuple(row[1:]) for row in rows}


async def test_every_public_table_is_under_forced_rls_with_a_policy(admin_engine):
    tables = await _public_tables(admin_engine)
    # Guards the query itself: an empty result would pass vacuously. messages
    # is named because it has no user_id column of its own.
    assert {
        "conversations",
        "messages",
        "documents",
        "chunks",
        "user_profiles",
    } <= set(tables)
    missing = {
        name: (enabled, forced, policies)
        for name, (enabled, forced, policies) in tables.items()
        if name not in EXEMPT and not (enabled and forced and policies >= 1)
    }
    # (relrowsecurity, relforcerowsecurity, policy count) per offending table.
    assert missing == {}


async def test_messages_is_under_forced_rls_with_a_policy(admin_engine):
    tables = await _public_tables(admin_engine)
    enabled, forced, policies = tables["messages"]
    assert enabled and forced and policies >= 1


async def test_the_exemptions_still_exist(admin_engine):
    # A renamed or dropped exempt table must leave this list, not linger in it.
    assert set(EXEMPT) <= set(await _public_tables(admin_engine))
