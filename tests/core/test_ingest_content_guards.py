"""Text uploads are decoded as UTF-8 with a leading byte-order mark dropped,
and text carrying a NUL character is refused as permanent: Postgres text
columns cannot store NUL, so the chunk insert would fail on every retry. The
refusal is user-visible, so it never echoes the file's content."""

import pytest

from packages.core.rag.errors import PermanentIngestError
from packages.core.rag.extract import extract_text


@pytest.mark.parametrize("filename", ["notes.txt", "notes.md"])
def test_leading_bom_is_dropped(filename):
    assert extract_text(b"\xef\xbb\xbfhello world", filename) == "hello world"


def test_text_without_bom_is_unchanged():
    assert extract_text(b"hello world", "notes.txt") == "hello world"


@pytest.mark.parametrize("filename", ["notes.txt", "notes.md"])
def test_nul_is_permanent_and_does_not_echo_content(filename):
    with pytest.raises(PermanentIngestError) as excinfo:
        extract_text(b"zebraquartz before\x00after zebraquartz", filename)

    message = str(excinfo.value)
    assert "nul" in message.lower()
    assert "zebraquartz" not in message


def test_nul_after_a_bom_is_still_refused():
    with pytest.raises(PermanentIngestError):
        extract_text(b"\xef\xbb\xbfabc\x00def", "notes.txt")
