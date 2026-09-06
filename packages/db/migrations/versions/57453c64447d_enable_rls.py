"""enable rls

Revision ID: 57453c64447d
Revises: f9fc01e849ec
Create Date: 2026-09-06 00:15:30.507302

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "57453c64447d"
down_revision: Union[str, Sequence[str], None] = "f9fc01e849ec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables with a direct user_id column. messages is handled separately (no
# user_id by design — always reached via its conversation).
#
# accounts and email_tokens also carry user_id but are deliberately NOT
# policied here: their consumers run pre-identity / without an announced
# user (oauth-upsert reached via internal_only's shared-secret auth,
# email-token verification during signup/password-reset before login), so
# RLS on them would zero out the exact flows that need to touch other users'
# rows before a session exists. Revisit once slices 3/4 land those access
# patterns and it's clear what identity (if any) is available at that point.
OWNED_TABLES = ("conversations", "documents", "chunks")

# NULLIF: after a SET LOCAL-bearing transaction ends, a custom GUC can read
# back as '' rather than NULL; ''::uuid would error every query. Either way
# the comparison is against NULL => no rows => fail-closed. A non-empty,
# non-UUID value (unreachable from the two verified writers — the begin
# listener always sets a real uuid.UUID; possible only via ContextVar misuse
# elsewhere) raises a cast ERROR instead of an empty result — still
# fail-closed, just via exception rather than zero rows.
_IDENT = "NULLIF(current_setting('app.current_user_id', true), '')::uuid"


def upgrade() -> None:
    # The app role must exist before policies are worth anything. Created by
    # infra/docker-compose/postgres/init.sql (dev), tests/api/conftest.py
    # (test/CI), Terraform at M3 (prod). Fail with instructions, not mid-way.
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hax_app') THEN
            RAISE EXCEPTION 'role hax_app missing — apply '
              'infra/docker-compose/postgres/init.sql first (see README auth setup)';
          END IF;
        END $$;
        """
    )

    for table in OWNED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE: policies bind even when the connecting role OWNS the table —
        # without it RLS is decorative wherever app == owner.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_owner ON {table}
            FOR ALL
            USING (user_id = {_IDENT})
            WITH CHECK (user_id = {_IDENT})
            """
        )

    op.execute("ALTER TABLE messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE messages FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY messages_owner ON messages
        FOR ALL
        USING (EXISTS (
            SELECT 1 FROM conversations c
            WHERE c.id = conversation_id AND c.user_id = {_IDENT}
        ))
        WITH CHECK (EXISTS (
            SELECT 1 FROM conversations c
            WHERE c.id = conversation_id AND c.user_id = {_IDENT}
        ))
        """
    )

    # Idempotent re-run of the app-role grants: covers databases where
    # init.sql never ran (hax_test via fixtures already grants; RDS at M3
    # gets them here).
    op.execute("GRANT USAGE ON SCHEMA public TO hax_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hax_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY messages_owner ON messages")
    op.execute("ALTER TABLE messages NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE messages DISABLE ROW LEVEL SECURITY")
    for table in reversed(OWNED_TABLES):
        op.execute(f"DROP POLICY {table}_owner ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    # Grants are left in place: harmless, and Task 0's init.sql owns them.
