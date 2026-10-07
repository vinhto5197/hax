import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.db.session import Base

if TYPE_CHECKING:
    from packages.db.models.conversation import Conversation


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="messages_role_check"),
        Index("messages_conv_created_idx", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
    )
    role: Mapped[str]
    content: Mapped[str]
    # User-facing provenance for an assistant turn: the retrieved passages the
    # model had in context, snapshotted (a later document delete does not
    # erase it). NULL unless the turn searched and found something. Never read
    # when the history is replayed to the model (load_history selects content).
    # none_as_null: a Python None must land as SQL NULL, not the JSON value
    # 'null', or "IS NULL" lies about every row written without sources.
    sources: Mapped[list[dict] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
