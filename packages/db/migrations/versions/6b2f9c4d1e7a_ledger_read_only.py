"""the migration ledger is read-only for the app role

Revision ID: 6b2f9c4d1e7a
Revises: 037453cacbe4
Create Date: 2026-10-05 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b2f9c4d1e7a"
down_revision: Union[str, Sequence[str], None] = "037453cacbe4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The blanket grant (57453c64447d) and the bootstrap's default privileges
    # gave hax_app write access to alembic_version. Only the owner (migrate)
    # ever writes it; an app-role foothold must not be able to rewrite which
    # revision the schema is at.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM hax_app")


def downgrade() -> None:
    op.execute("GRANT INSERT, UPDATE, DELETE ON alembic_version TO hax_app")
