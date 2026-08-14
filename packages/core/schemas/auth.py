from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SignupIn(BaseModel):
    email: EmailStr
    # Length-only policy (spec: Flows); the cap bounds argon2 work per attempt.
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=200)


class SignupOut(BaseModel):
    id: UUID
    email: str


class CredentialsIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AuthUserOut(BaseModel):
    id: UUID
    email: str
    name: str | None
