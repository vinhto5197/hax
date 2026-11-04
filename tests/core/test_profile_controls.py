"""ProfileIn.about rejects C0 control characters (NUL and U+0001-U+001F) other
than tab, newline and carriage return, the same rule as ChatRequest.prompt; the
ValidationError (a 422 at the API) points at ``about`` and names control
characters in plain text. Surrounding whitespace is stripped first.
"""

import pytest
from pydantic import ValidationError

from packages.core.schemas.profile import ProfileIn


def _assert_about_rejected(about: str) -> None:
    with pytest.raises(ValidationError) as exc:
        ProfileIn(about=about)
    err = exc.value.errors()[0]
    assert err["loc"] == ("about",)
    assert "control" in err["msg"].lower()


def test_nul_inside_about_rejected():
    _assert_about_rejected("I am a\x00 backend engineer")


@pytest.mark.parametrize("ch", ["\x01", "\x07", "\x08", "\x0b", "\x0c", "\x1b", "\x1f"])
def test_other_control_char_rejected_inside_text(ch):
    _assert_about_rejected(f"I prefer terse{ch} answers with code")


@pytest.mark.parametrize(
    "about",
    ["col1\tcol2", "line one\nline two", "line one\r\nline two", "a\tb\nc\rd"],
)
def test_tab_newline_cr_accepted_and_preserved(about):
    assert ProfileIn(about=about).about == about


def test_allowed_whitespace_still_stripped_at_edges():
    assert ProfileIn(about="\n\thi\tthere\r\n").about == "hi\tthere"


def test_over_1000_characters_after_strip_still_rejected():
    with pytest.raises(ValidationError) as exc:
        ProfileIn(about="  " + "x" * 1001 + "  ")
    assert exc.value.errors()[0]["loc"] == ("about",)
