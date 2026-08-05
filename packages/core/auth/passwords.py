"""Password hashing (argon2id) for the credentials login method.

Cross-module contract: hashes written by hash_password are verified only by
verify_password; dummy_verify exists so an unknown-email login burns the same
argon2 work as a real mismatch (timing-equalized checks — spec threat table).
M3 note: argon2 default memory_cost (~64 MiB/hash) × concurrent logins needs
a look at deploy sizing.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# Precomputed at import so dummy_verify's cost matches a real verification.
_DUMMY_HASH = _hasher.hash("hax-dummy-password-for-timing-only")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify(password: str) -> None:
    try:
        _hasher.verify(_DUMMY_HASH, password)
    except VerifyMismatchError:
        pass
