import uuid

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.session import Base

# Mirrored by ProfileIn's cap (packages/core/schemas/profile.py); char_length
# counts code points, as Python's len does.
ABOUT_MAX_CHARS = 1000


class UserProfile(Base):
    """A member's note about themselves. Owned content under FORCE RLS, one
    row per user; no row means no note (an empty note is deleted, never
    stored)."""

    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            f"char_length(about) BETWEEN 1 AND {ABOUT_MAX_CHARS}",
            name="user_profiles_about_length_check",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    about: Mapped[str]
