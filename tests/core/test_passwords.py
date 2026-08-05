from packages.core.auth.passwords import dummy_verify, hash_password, verify_password


def test_hash_is_not_plaintext_and_verifies():
    h = hash_password("correct horse battery staple")
    assert "correct horse" not in h
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery staple") is True


def test_wrong_password_fails():
    h = hash_password("right")
    assert verify_password(h, "wrong") is False


def test_garbage_hash_fails_not_raises():
    assert verify_password("not-a-hash", "anything") is False


def test_two_hashes_of_same_password_differ():
    # Per-hash random salt — equal hashes would mean a broken salt.
    assert hash_password("same") != hash_password("same")


def test_dummy_verify_swallows_result():
    assert dummy_verify("whatever") is None
