import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.db.session import Base

if TYPE_CHECKING:
    from packages.db.models.chunk import Chunk

# Ingestion lifecycle, driven by the Celery worker.
DOCUMENT_STATUSES = ("pending", "processing", "ready", "failed")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # CHECK derived from DOCUMENT_STATUSES (local constants — no injection
        # risk); Alembic autogenerate flags drift against the migration's literal.
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in DOCUMENT_STATUSES) + ")",
            name="documents_status_check",
        ),
        Index("documents_user_id_idx", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    filename: Mapped[str]
    mime_type: Mapped[str]
    size_bytes: Mapped[int]
    # Object-storage key for the raw bytes; the worker reads the file back by it.
    # Nullable: docs ingested before object storage existed have none.
    storage_key: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(server_default="pending")
    error: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # passive_deletes: let the DB's ON DELETE CASCADE remove chunks instead of
    # the ORM loading every embedding just to emit per-row DELETEs.
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
