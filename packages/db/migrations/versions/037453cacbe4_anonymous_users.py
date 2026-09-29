"""anonymous users

Revision ID: 037453cacbe4
Revises: 57453c64447d
Create Date: 2026-09-28 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "037453cacbe4"
down_revision: Union[str, Sequence[str], None] = "57453c64447d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # An anonymous row has no email. users_email_lower_idx (unique on
    # lower(email)) ignores NULLs, so it needs no change.
    op.alter_column("users", "email", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # Fails if anonymous (email IS NULL) rows exist; delete them first.
    op.alter_column("users", "email", existing_type=sa.String(), nullable=False)
