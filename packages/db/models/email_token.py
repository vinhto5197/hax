import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.session import Base

EMAIL_TOKEN_PURPOSES = ("verify_email", "reset_password")


class EmailToken(Base):
    """Single-use inbox-ownership proof (verification + password reset).

    Only the sha256 of the 256-bit random token is stored; the raw token
    exists solely in the emailed link. used_at marks consumption — a token is
    valid iff unused, unexpired, and purpose-matched (slice 4 enforces).
    """

    __tablename__ = "email_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN (" + ", ".join(f"'{p}'" for p in EMAIL_TOKEN_PURPOSES) + ")",
            name="email_tokens_purpose_check",
        ),
        Index("email_tokens_user_purpose_idx", "user_id", "purpose"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(unique=True)
    purpose: Mapped[str]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
