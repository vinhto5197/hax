"""conversations streaming since

Revision ID: a674bffd34c0
Revises: ab6909812679
Create Date: 2026-10-21 22:15:08.972785

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a674bffd34c0"
down_revision: Union[str, Sequence[str], None] = "ab6909812679"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("streaming_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "streaming_since")
