"""user profiles

Revision ID: c3e8a1f05b92
Revises: a674bffd34c0
Create Date: 2026-10-28 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3e8a1f05b92"
down_revision: Union[str, Sequence[str], None] = "a674bffd34c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same identity expression as the other owned tables (57453c64447d): an unset
# or empty GUC compares against NULL, so no rows (fail-closed).
_IDENT = "NULLIF(current_setting('app.current_user_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("about", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "char_length(about) BETWEEN 1 AND 1000",
            name="user_profiles_about_length_check",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.execute("ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_profiles FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY user_profiles_owner ON user_profiles
        FOR ALL
        USING (user_id = {_IDENT})
        WITH CHECK (user_id = {_IDENT})
        """
    )
    # Default privileges cover tables created by the role named `hax`; this
    # keeps the table usable where the owner role is named otherwise.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_profiles TO hax_app")


def downgrade() -> None:
    op.drop_table("user_profiles")
