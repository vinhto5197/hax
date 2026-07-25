import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.db.session import Base

if TYPE_CHECKING:
    from packages.db.models.document import Document

# Must match the embedding model's output dimension; changing it means a
# migration AND re-embedding the corpus (ADR 0007).
EMBEDDING_DIM = 1024


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        # HNSW index over cosine distance (<=>). Makes top-k retrieval an
        # approximate-nearest-neighbour index scan instead of a full table scan.
        Index(
            "chunks_embedding_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
    )
    # Denormalized from documents for the M2.5 per-user retrieval filter.
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Position within the source document.
    idx: Mapped[int]
    content: Mapped[str]
    # 'metadata' is reserved on the Declarative Base, so the attribute is
    # chunk_metadata while the column stays 'metadata'. Carries the filename for
    # retrieval-time labelling without a join.
    chunk_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")
