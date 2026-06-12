import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.db.session import Base

if TYPE_CHECKING:
    from packages.db.models.chunk import Chunk

# Ingestion lifecycle. In slice 1 ingestion is synchronous, so a document goes
# pending -> ready|failed inside one request; `processing` becomes meaningful
# when Celery owns the pipeline (M2 slice 2).
DOCUMENT_STATUSES = ("pending", "processing", "ready", "failed")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # Single source of truth: derive the CHECK from DOCUMENT_STATUSES (values
        # are local constants — no injection risk). The migration keeps its own
        # frozen literal; Alembic autogenerate flags any drift between them.
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in DOCUMENT_STATUSES) + ")",
            name="documents_status_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    # Nullable until M2.5 adds auth + backfills; no per-user filter yet.
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    filename: Mapped[str]
    mime_type: Mapped[str]
    size_bytes: Mapped[int]
    status: Mapped[str] = mapped_column(server_default="pending")
    error: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
