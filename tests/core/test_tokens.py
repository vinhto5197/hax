import time
import uuid

import jwt
import pytest

from packages.core.auth.tokens import (
    ALGORITHM,
    AUDIENCE,
    ISSUER,
    InvalidSessionToken,
    SessionClaims,
    decode_session_token,
)

SECRET = "unit-test-secret-padded-to-32-bytes!!"
UID = str(uuid.uuid4())


def mint(secret=SECRET, alg=ALGORITHM, **overrides):
    now = int(time.time())
    payload = {
        "sub": UID,
        "email": "a@example.com",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 600,
        "jti": "j1",
        "auth_time": now,
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, secret, algorithm=alg)


def test_valid_token_decodes():
    claims = decode_session_token(mint(), SECRET)
    assert isinstance(claims, SessionClaims)
    assert str(claims.sub) == UID
    assert claims.email == "a@example.com"


def test_wrong_secret_rejected():
    with pytest.raises(InvalidSessionToken):
        decode_session_token(
            mint(secret="a-different-secret-also-32-bytes-long!!"), SECRET
        )


def test_expired_rejected():
    with pytest.raises(InvalidSessionToken):
        decode_session_token(mint(exp=int(time.time()) - 10), SECRET)


def test_wrong_audience_rejected():
    with pytest.raises(InvalidSessionToken):
        decode_session_token(mint(aud="other-api"), SECRET)


def test_wrong_issuer_rejected():
    with pytest.raises(InvalidSessionToken):
        decode_session_token(mint(iss="evil"), SECRET)


def test_alg_none_rejected():
    # The classic bypass: header claims alg=none. Pinned algorithms must kill it.
    from jwt.utils import base64url_encode

    parts = mint().split(".")
    forged = (
        base64url_encode(b'{"alg":"none","typ":"JWT"}').decode() + "." + parts[1] + "."
    )
    with pytest.raises(InvalidSessionToken):
        decode_session_token(forged, SECRET)


def test_missing_auth_time_rejected():
    with pytest.raises(InvalidSessionToken):
        decode_session_token(mint(auth_time=None), SECRET)


def test_non_uuid_sub_rejected():
    with pytest.raises(InvalidSessionToken):
        decode_session_token(mint(sub="admin"), SECRET)
