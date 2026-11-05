"""add documents storage_key

Revision ID: 60d8ab46909b
Revises: 15726f3eafd7
Create Date: 2026-06-30 16:34:49.350892

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "60d8ab46909b"
down_revision: Union[str, Sequence[str], None] = "15726f3eafd7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("storage_key", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "storage_key")
