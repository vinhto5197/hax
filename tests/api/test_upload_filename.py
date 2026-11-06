"""An upload's filename is validated before anything else happens to it: a
name holding a NUL byte or another C0 control character, or longer than 255
characters, is a 400 with a string detail. A refused name leaves no document
row and does not spend an upload slot. A name of exactly 255 characters is
accepted.

The multipart body is built by hand: httpx percent-encodes control
characters in a filename, so a test through `files=` would never send the
raw byte. A raw newline cannot be sent at all — it ends the part's header
line — so the C0 cases stop short of LF and CR.
"""

import uuid

import pytest

import apps.api.routers.documents as documents_router
from tests.api.conftest import bearer

MAX_NAME = 255


def _multipart(filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"hax-{uuid.uuid4().hex}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode("latin-1")
    body = head + content + f"\r\n--{boundary}--\r\n".encode("latin-1")
    return body, f"multipart/form-data; boundary={boundary}"


async def _upload_raw(client, user, filename: str, content: bytes = b"hello world"):
    body, content_type = _multipart(filename, content)
    return await client.post(
        "/api/documents",
        content=body,
        headers={**bearer(user), "Content-Type": content_type},
    )


async def _upload(client, user, name="ok.txt", content=b"hello world"):
    return await client.post(
        "/api/documents",
        files={"file": (name, content, "text/plain")},
        headers=bearer(user),
    )


async def _listing(client, user) -> list[dict]:
    r = await client.get("/api/documents", headers=bearer(user))
    assert r.status_code == 200
    return r.json()


async def _assert_refused_cleanly(client, user, r) -> None:
    """400, string detail, no row; and the next valid upload within an hourly
    cap of one still succeeds, so the refusal spent no slot."""
    assert r.status_code == 400, r.text
    assert isinstance(r.json()["detail"], str)
    assert await _listing(client, user) == []
    assert (await _upload(client, user, "ok.txt")).status_code == 200


async def test_a_filename_containing_a_nul_byte_is_refused_with_400_stores_nothing_and_spends_no_upload_slot(  # noqa: E501 — the name is the behaviour line
    client, user_a, stub_storage, monkeypatch
):
    monkeypatch.setattr(documents_router, "UPLOADS_PER_HOUR", 1)

    r = await _upload_raw(client, user_a, "notes\x00.txt")

    await _assert_refused_cleanly(client, user_a, r)


@pytest.mark.parametrize(
    "char",
    ["\x01", "\x07", "\x08", "\x1b", "\x1f"],
    ids=["soh", "bel", "bs", "esc", "us"],
)
async def test_a_filename_containing_another_c0_control_character_is_refused_with_400_stores_nothing_and_spends_no_upload_slot(  # noqa: E501 — the name is the behaviour line
    client, user_a, stub_storage, monkeypatch, char
):
    monkeypatch.setattr(documents_router, "UPLOADS_PER_HOUR", 1)

    r = await _upload_raw(client, user_a, f"not{char}es.txt")

    await _assert_refused_cleanly(client, user_a, r)


async def test_a_filename_longer_than_255_characters_is_refused_with_400_stores_nothing_and_spends_no_upload_slot(  # noqa: E501 — the name is the behaviour line
    client, user_a, stub_storage, monkeypatch
):
    monkeypatch.setattr(documents_router, "UPLOADS_PER_HOUR", 1)
    name = "a" * (MAX_NAME + 1 - len(".txt")) + ".txt"
    assert len(name) == MAX_NAME + 1

    r = await _upload(client, user_a, name)

    await _assert_refused_cleanly(client, user_a, r)


async def test_a_filename_of_exactly_255_characters_with_a_valid_suffix_is_accepted(
    client, user_a, stub_storage
):
    name = "a" * (MAX_NAME - len(".txt")) + ".txt"
    assert len(name) == MAX_NAME

    r = await _upload(client, user_a, name)

    assert r.status_code == 200, r.text
    assert r.json()["filename"] == name
    assert [d["filename"] for d in await _listing(client, user_a)] == [name]


# Non-ASCII names go through httpx's `files=`, which sends the filename as raw
# UTF-8 in the Content-Disposition header (no filename*), as a browser does.
# The storage key is documents/<uuid>/<name>, and S3 caps a key at 1024 bytes.
CJK = "文"  # 3 bytes in UTF-8
EMOJI = "\U0001f600"  # 4 bytes in UTF-8


async def test_a_filename_of_255_characters_mostly_three_byte_utf8_is_accepted(
    client, user_a, stub_storage
):
    name = CJK * (MAX_NAME - len(".txt")) + ".txt"
    assert len(name) == MAX_NAME
    assert len(name.encode()) > MAX_NAME  # the limit counts characters, not bytes

    r = await _upload(client, user_a, name)

    assert r.status_code == 200, r.text
    assert r.json()["filename"] == name
    assert [d["filename"] for d in await _listing(client, user_a)] == [name]


async def test_a_filename_of_255_four_byte_characters_too_long_for_the_storage_key_is_refused_with_400_stores_nothing_and_spends_no_upload_slot(  # noqa: E501 — the name is the behaviour line
    client, user_a, stub_storage, monkeypatch
):
    monkeypatch.setattr(documents_router, "UPLOADS_PER_HOUR", 1)
    name = EMOJI * (MAX_NAME - len(".txt")) + ".txt"
    assert len(name) == MAX_NAME
    assert len(f"documents/{uuid.uuid4()}/{name}".encode()) > 1024

    r = await _upload(client, user_a, name)

    await _assert_refused_cleanly(client, user_a, r)
