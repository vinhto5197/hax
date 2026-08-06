"""Session-JWT verification — the FastAPI half of the Auth.js bridge.

Cross-module contract with apps/web/auth.ts (the minting half): HS256, shared
AUTH_SECRET, iss "hax", aud "hax-api", claims sub/email/iat/exp/jti/auth_time.
auth_time is the LOGIN moment and is preserved across Auth.js re-issues —
revocation compares it to users.sessions_valid_after, so a re-issue must never
carry a fresher auth_time than the login that produced it.
"""

import uuid

import jwt
from pydantic import BaseModel

ISSUER = "hax"
AUDIENCE = "hax-api"
ALGORITHM = "HS256"


class InvalidSessionToken(Exception):
    """Signature, expiry, claim-shape, or issuer/audience failure."""


class SessionClaims(BaseModel):
    sub: uuid.UUID
    email: str
    auth_time: int
    jti: str


def decode_session_token(token: str, secret: str) -> SessionClaims:
    try:
        payload = jwt.decode(
            token,
            secret,
            # Pinned list — never read the algorithm from the token's header.
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.InvalidTokenError as exc:
        raise InvalidSessionToken(str(exc)) from exc
    try:
        return SessionClaims(
            sub=uuid.UUID(str(payload["sub"])),
            email=str(payload["email"]),
            auth_time=int(payload["auth_time"]),
            jti=str(payload.get("jti", "")),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidSessionToken(f"malformed claims: {exc}") from exc
