import uuid
from datetime import UTC, datetime

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
    # NULL = an anonymous demo visitor, and nothing else: every other user has
    # an address. Signup while anonymous writes the address onto this row; the
    # visitor's token still carries no email, so the demo caps hold until they
    # verify and log in again (the login gate refuses unverified accounts).
    email: Mapped[str | None] = mapped_column(nullable=True)
    name: Mapped[str | None] = mapped_column(nullable=True)
    # NULL = no password method attached (Google-born account); the reset flow
    # is what adds a password to such an account.
    password_hash: Mapped[str | None] = mapped_column(nullable=True)
    # NULL = unverified. The login gate on this defaults ON
    # (AUTH_REQUIRE_EMAIL_VERIFICATION); verification, reset, and a
    # provider-verified claim stamp it.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Revocation cutoff: tokens whose auth_time predates this are dead.
    # Password reset bumps it (DB + Redis write-through — see apps/api/auth.py).
    # One clock, the app's: every later writer stamps datetime.now(UTC), and
    # auth_time in the token is the app clock too. A DB-clock insert default
    # would sit tens of ms ahead of the app (RDS and the box are different
    # machines), so a bump made moments after signup could land BEFORE the
    # birth stamp, and a token minted in the same second as a cutoff could
    # read as revoked. server_default remains for non-ORM inserts only.
    sessions_valid_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
