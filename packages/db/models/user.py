import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.session import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Case-insensitive uniqueness: the app lowercases at the boundary, the
        # index enforces it against any path that forgets.
        Index("users_email_lower_idx", text("lower(email)"), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str]
    name: Mapped[str | None] = mapped_column(nullable=True)
    # NULL = no password method attached (Google-born account); the reset flow
    # (slice 4) is what adds a password to such an account.
    password_hash: Mapped[str | None] = mapped_column(nullable=True)
    # NULL = unverified. The login gate on this is env-switched OFF until
    # slice 4 ships verification emails.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Revocation cutoff: tokens whose auth_time predates this are dead.
    # Password reset bumps it (DB + Redis write-through — see apps/api/auth.py).
    sessions_valid_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
