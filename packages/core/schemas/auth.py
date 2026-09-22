from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SignupIn(BaseModel):
    email: EmailStr
    # Length-only policy; the cap bounds argon2 work per attempt.
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=200)


class AcceptedOut(BaseModel):
    # One body for every input on the anti-enumeration routes.
    # A model, not a bare string: FastAPI derives the OpenAPI/TypeScript type
    # from it (a literal "check_inbox", not string), every route returns an
    # object, and an object can gain a field without breaking readers of
    # .status.
    status: Literal["check_inbox"] = "check_inbox"


class EmailIn(BaseModel):
    email: EmailStr


class CredentialsIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AuthUserOut(BaseModel):
    id: UUID
    email: str
    name: str | None


class TokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=128)


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=128)


class EmailOut(BaseModel):
    email: str


class TokenStatusOut(BaseModel):
    status: Literal["valid"] = "valid"


class OAuthUpsertIn(BaseModel):
    # Closed set: a provider name is a trust decision (which issuer's
    # email_verified we believe), so adding one is a code change, not data.
    provider: Literal["google"]
    provider_account_id: str = Field(min_length=1, max_length=255)
    email: EmailStr
    email_verified: bool
    name: str | None = Field(default=None, max_length=200)
