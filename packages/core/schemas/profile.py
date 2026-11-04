"""A member's note about themselves: the body PUT /api/me/profile parses and
the body both profile routes return."""

from pydantic import BaseModel, field_validator

from packages.core.schemas.chat import _no_control_chars
from packages.db.models.user_profile import ABOUT_MAX_CHARS


class ProfileIn(BaseModel):
    about: str

    # The cap applies after the strip, so trailing whitespace on a full note
    # still saves; len counts code points, as the CHECK's char_length does.
    # C0 controls other than tab, newline and CR are refused by the same rule
    # as ChatRequest.prompt (NUL also because Postgres text cannot store it).
    @field_validator("about")
    @classmethod
    def _strip_and_cap(cls, value: str) -> str:
        value = value.strip()
        _no_control_chars(value)
        if len(value) > ABOUT_MAX_CHARS:
            raise ValueError(f"must be at most {ABOUT_MAX_CHARS} characters")
        return value


class ProfileOut(BaseModel):
    about: str | None
