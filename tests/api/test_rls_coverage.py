"""Every table with a `user_id` column is under row-level security, enabled
and FORCEd, with at least one policy — read from the catalog, so a new
user-scoped table that ships without RLS fails here rather than in a review.

The exemptions are ADR 0012's standing decision: `accounts` and
`email_tokens` serve pre-session flows and are bounded by their repo
modules instead. Adding a table to EXEMPT is a decision for that ADR."""

from sqlalchemy import text

EXEMPT = {"accounts", "email_tokens"}


async def _user_scoped_tables(admin_engine) -> dict[str, tuple[bool, bool, int]]:
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,"
                "  (SELECT count(*) FROM pg_policies p"
                "    WHERE p.schemaname = 'public' AND p.tablename = c.relname)"
                " FROM pg_class c"
                " JOIN pg_namespace n ON n.oid = c.relnamespace"
                " JOIN pg_attribute a ON a.attrelid = c.oid"
                " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
                "  AND a.attname = 'user_id' AND NOT a.attisdropped"
            )
        )
        return {row[0]: tuple(row[1:]) for row in rows}


async def test_every_user_scoped_table_is_under_forced_rls_with_a_policy(
    admin_engine,
):
    tables = await _user_scoped_tables(admin_engine)
    # Guards the query itself: an empty result would pass vacuously.
    assert {"conversations", "documents", "chunks", "user_profiles"} <= set(tables)
    missing = {
        name: (enabled, forced, policies)
        for name, (enabled, forced, policies) in tables.items()
        if name not in EXEMPT and not (enabled and forced and policies >= 1)
    }
    # (relrowsecurity, relforcerowsecurity, policy count) per offending table.
    assert missing == {}


async def test_the_exemptions_still_exist(admin_engine):
    # A renamed or dropped exempt table must leave this list, not linger in it.
    assert EXEMPT <= set(await _user_scoped_tables(admin_engine))
