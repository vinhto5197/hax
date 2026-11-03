"""user_profiles about as varchar

Revision ID: e5b2f8c3d7a1
Revises: d41c7e2a9b10
Create Date: 2026-11-03 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b2f8c3d7a1"
down_revision: Union[str, Sequence[str], None] = "d41c7e2a9b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every other text column is String (VARCHAR); this one was created as
    # TEXT. Postgres converts text to varchar without rewriting the table.
    op.alter_column(
        "user_profiles",
        "about",
        type_=sa.String(),
        existing_type=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "user_profiles",
        "about",
        type_=sa.Text(),
        existing_type=sa.String(),
        existing_nullable=False,
    )
