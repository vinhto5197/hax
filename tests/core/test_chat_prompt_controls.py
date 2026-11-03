"""ChatRequest.prompt rejects C0 control characters (NUL and U+0001-U+001F)
other than tab, newline and carriage return; the ValidationError (a 422 at the
API) points at ``prompt`` and names control characters in plain text.
"""

import pytest
from pydantic import ValidationError

from packages.core.schemas.chat import ChatRequest


def _assert_prompt_rejected(prompt: str) -> None:
    with pytest.raises(ValidationError) as exc:
        ChatRequest(prompt=prompt)
    err = exc.value.errors()[0]
    assert err["loc"] == ("prompt",)
    assert "control" in err["msg"].lower()


def test_nul_inside_prompt_rejected():
    _assert_prompt_rejected("hello\x00world")


@pytest.mark.parametrize("ch", ["\x01", "\x07", "\x08", "\x0b", "\x0c", "\x1b", "\x1f"])
def test_other_control_char_rejected_inside_text(ch):
    _assert_prompt_rejected(f"what is in my notes{ch} about taxes?")


@pytest.mark.parametrize(
    "prompt",
    ["col1\tcol2", "line one\nline two", "line one\r\nline two", "a\tb\nc\rd"],
)
def test_tab_newline_cr_accepted_and_preserved(prompt):
    assert ChatRequest(prompt=prompt).prompt == prompt


def test_allowed_whitespace_still_stripped_at_edges():
    assert ChatRequest(prompt="\n\thi\tthere\r\n").prompt == "hi\tthere"
