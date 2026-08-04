import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.session import Base


class Account(Base):
    """One linked OAuth identity: (provider, provider_account_id) -> user.

    Linking rules live in the API (oauth-upsert, slice 3): an identity may
    attach to an existing user only when the provider asserts the email is
    verified — this table just guarantees an identity can't attach twice.
    """

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_account_id", name="accounts_provider_account_uq"
        ),
        Index("accounts_user_id_idx", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    provider: Mapped[str]
    provider_account_id: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
