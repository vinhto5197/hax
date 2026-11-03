"""chunks document_id index

Revision ID: d41c7e2a9b10
Revises: c3e8a1f05b92
Create Date: 2026-11-03 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d41c7e2a9b10"
down_revision: Union[str, Sequence[str], None] = "c3e8a1f05b92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A plain build blocks writes to chunks (ingestion) while it runs, which
    # at this table's size is well under a second; CONCURRENTLY would need
    # its own non-transactional migration for no gain here.
    op.create_index("chunks_document_id_idx", "chunks", ["document_id"])


def downgrade() -> None:
    op.drop_index("chunks_document_id_idx", table_name="chunks")
