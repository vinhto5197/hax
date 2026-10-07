"""messages carry sources

Revision ID: ab6909812679
Revises: 6b2f9c4d1e7a
Create Date: 2026-10-06 14:48:26.626840

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ab6909812679"
down_revision: Union[str, Sequence[str], None] = "6b2f9c4d1e7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "sources")
