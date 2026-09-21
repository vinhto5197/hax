from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from packages.core import titles


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"Quarterly Sales Summary."', "Quarterly Sales Summary"),
        ("  Planning   a\nTrip to Hanoi  ", "Planning a Trip to Hanoi"),
        ("", None),
        ('""', None),
        ("x" * 80, "x" * 80),
        # Over the limit: cut at a word boundary, never mid-word, "…" marks it.
        ("x" * 200, "x" * 79 + "…"),
        ("x" * 70 + " yyyyyyyyyyyyyyy", "x" * 70 + "…"),
        ("x" * 69 + ", yyyyyyyyyyyyyyy", "x" * 69 + "…"),
    ],
)
def test_clean_title(raw, expected):
    assert titles.clean_title(raw) == expected


def test_cut_title_fits_the_limit_and_ends_on_a_whole_word():
    cut = titles.clean_title("alpha beta " * 20)
    assert len(cut) <= titles.MAX_TITLE_CHARS
    assert cut.endswith(("alpha…", "beta…"))


def _reply(text='{"title": "Trip Planning Notes"}', stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
    )


@pytest.fixture
def fake_create(monkeypatch):
    """Fakes AsyncAnthropic itself (not an instance): suggest_title builds a
    fresh client per call, so the fixture must intercept the constructor and
    hand back something usable as `async with ... as client`."""
    create = AsyncMock(return_value=_reply())
    state = {"kwargs": None, "closed": False}

    class FakeClient:
        def __init__(self, **kwargs):
            state["kwargs"] = kwargs
            self.messages = SimpleNamespace(create=create)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            state["closed"] = True

    monkeypatch.setattr(titles, "AsyncAnthropic", FakeClient)
    create.state = state
    return create


async def test_suggest_title_calls_the_small_model_with_the_message(fake_create):
    assert await titles.suggest_title("plan a trip to hanoi") == "Trip Planning Notes"
    kwargs = fake_create.call_args.kwargs
    assert kwargs["model"] == titles.TITLE_MODEL
    assert kwargs["max_tokens"] == titles.MAX_OUTPUT_TOKENS
    assert kwargs["messages"] == [{"role": "user", "content": "plan a trip to hanoi"}]
    assert "title" in kwargs["system"].lower()
    # The user's message is data, not instructions — pin the guardrail wording
    # and the call shape (no tools/stream/temperature/thinking).
    assert "not instructions" in kwargs["system"]
    assert set(kwargs) == {"model", "max_tokens", "system", "messages", "output_config"}
    # The reply shape is constrained at the source: one required string field.
    schema = kwargs["output_config"]["format"]["schema"]
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert schema["required"] == ["title"]
    assert schema["properties"] == {"title": {"type": "string"}}
    assert schema["additionalProperties"] is False
    assert fake_create.state["kwargs"] == {"timeout": 20.0, "max_retries": 1}
    assert fake_create.state["closed"] is True  # client closed with the call


async def test_long_message_is_truncated_before_sending(fake_create):
    await titles.suggest_title("u" * 5000)
    content = fake_create.call_args.kwargs["messages"][0]["content"]
    assert len(content) == titles.MAX_INPUT_CHARS


async def test_refusal_or_empty_reply_gives_no_title(fake_create):
    fake_create.return_value = _reply(stop_reason="refusal")
    assert await titles.suggest_title("x") is None
    fake_create.return_value = _reply(text='{"title": "   "}')
    assert await titles.suggest_title("x") is None


@pytest.mark.parametrize("text", ["not json", "[]", "{}", '{"title": 7}', ""])
async def test_reply_without_a_title_string_gives_no_title(fake_create, text):
    fake_create.return_value = _reply(text=text)
    assert await titles.suggest_title("x") is None


async def test_max_tokens_stop_gives_no_title(fake_create):
    # A reply cut off at the token cap is incomplete JSON, not a usable title.
    fake_create.return_value = _reply(stop_reason="max_tokens")
    assert await titles.suggest_title("x") is None


async def test_non_text_blocks_are_ignored(fake_create):
    fake_create.return_value = SimpleNamespace(
        stop_reason="end_turn",
        content=[
            SimpleNamespace(type="thinking", thinking="…"),
            SimpleNamespace(type="text", text='{"title": "Real Title"}'),
        ],
    )
    assert await titles.suggest_title("x") == "Real Title"
