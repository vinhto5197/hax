"""The harness's two observation hooks: on_usage once per model call (the
MAX_ITERS fallback included) and on_tool_result once per executed tool_use.
Without them the yielded events are unchanged. Scripted fake client; no
network."""

import pytest

from packages.core.agent import harness
from tests.core.fake_anthropic import FakeClient, collect, text_block, tool_use, usage

MODEL = "claude-test-model"


def tool_turn(name="calculator", inp=None, u=None, id_="tu_1"):
    return {
        "text": [],
        "content": [
            tool_use(name, inp if inp is not None else {"expression": "2 + 3"}, id_)
        ],
        "stop_reason": "tool_use",
        "usage": u or usage(),
    }


def answer_turn(text="It is 5.", u=None):
    return {
        "text": [text],
        "content": [text_block(text)],
        "stop_reason": "end_turn",
        "usage": u or usage(),
    }


def _run(ctx, **kw):
    return collect(
        harness.stream_completion_agentic(
            [{"role": "user", "content": "what is 2 + 3?"}], model=MODEL, ctx=ctx, **kw
        )
    )


async def test_on_usage_called_once_per_model_call(monkeypatch, ctx):
    # None cache counts become 0 ("or 0"); set counts pass through.
    client = FakeClient(
        [
            tool_turn(u=usage(inp=100, out=20, cache_read=None, cache_write=7)),
            answer_turn(u=usage(inp=130, out=9, cache_read=11, cache_write=None)),
        ]
    )
    monkeypatch.setattr(harness, "_client", client)
    seen = []

    await _run(ctx, on_usage=seen.append)

    assert seen == [
        {"model": MODEL, "input": 100, "output": 20, "cache_read": 0, "cache_write": 7},
        {"model": MODEL, "input": 130, "output": 9, "cache_read": 11, "cache_write": 0},
    ]
    assert [c["model"] for c in client.calls] == [MODEL, MODEL]
    assert set(harness.Usage.__annotations__) == {
        "model",
        "input",
        "output",
        "cache_read",
        "cache_write",
    }


async def test_on_usage_called_for_the_fallback(monkeypatch, ctx):
    turns = [
        tool_turn(u=usage(inp=10 + i), id_=f"tu_{i}") for i in range(harness.MAX_ITERS)
    ] + [answer_turn("Forced.", u=usage(inp=999))]
    client = FakeClient(turns)
    monkeypatch.setattr(harness, "_client", client)
    seen = []

    events = await _run(ctx, on_usage=seen.append)

    assert events[-1] == {"content": "Forced."}
    assert "tools" not in client.calls[-1]  # the fallback call was made
    assert len(seen) == harness.MAX_ITERS + 1
    assert [u["input"] for u in seen] == [10 + i for i in range(harness.MAX_ITERS)] + [
        999
    ]
    assert all(u["model"] == MODEL for u in seen)


async def test_on_tool_result_gets_name_input_output(monkeypatch, ctx):
    sent = {"expression": "2 + 3"}
    client = FakeClient([tool_turn("calculator", sent), answer_turn()])
    monkeypatch.setattr(harness, "_client", client)
    seen = []

    await _run(ctx, on_tool_result=seen.append)

    assert seen == [
        {
            "name": "calculator",
            "input": {"expression": "2 + 3"},
            "output": "5",
            "is_error": False,
        }
    ]
    # `output` is exactly what the model received.
    [block] = client.calls[1]["messages"][-1]["content"]
    assert block["content"] == seen[0]["output"]
    assert set(harness.ToolResult.__annotations__) == {
        "name",
        "input",
        "output",
        "is_error",
    }


async def test_on_tool_result_reports_errors(monkeypatch, ctx):
    client = FakeClient(
        [tool_turn("no_such_tool", {"x": 1}), answer_turn("I could not do that.")]
    )
    monkeypatch.setattr(harness, "_client", client)
    seen = []

    await _run(ctx, on_tool_result=seen.append)

    assert len(seen) == 1
    [result] = seen
    assert result["name"] == "no_such_tool"
    assert result["input"] == {"x": 1}
    assert result["is_error"] is True
    [block] = client.calls[1]["messages"][-1]["content"]
    assert block["is_error"] is True
    assert block["content"] == result["output"]


async def test_without_hooks_the_events_are_unchanged(monkeypatch, ctx):
    def script():
        return [
            tool_turn("calculator", {"expression": "6 * 7"}),
            tool_turn("no_such_tool", {}, id_="tu_2"),
            answer_turn("42."),
        ]

    monkeypatch.setattr(harness, "_client", FakeClient(script()))
    plain = await _run(ctx)

    monkeypatch.setattr(harness, "_client", FakeClient(script()))
    hooked = await _run(ctx, on_usage=lambda u: None, on_tool_result=lambda r: None)

    assert plain  # the turn yielded something to compare
    assert hooked == plain


async def test_an_observer_that_raises_ends_the_turn(monkeypatch, ctx):
    # The contract (ADR 0002 addendum): observers are unguarded.
    client = FakeClient([tool_turn("calculator"), answer_turn()])
    monkeypatch.setattr(harness, "_client", client)

    def boom(_result):
        raise RuntimeError("observer bug")

    with pytest.raises(RuntimeError, match="observer bug"):
        await _run(ctx, on_tool_result=boom)
    assert len(client.calls) == 1  # no second model call after the raise


async def test_the_observer_cannot_change_what_the_model_sees(monkeypatch, ctx):
    client = FakeClient(
        [tool_turn("calculator", {"expression": "2 + 3"}), answer_turn()]
    )
    monkeypatch.setattr(harness, "_client", client)

    def scrub(result):
        result["input"]["expression"] = "REDACTED"

    await _run(ctx, on_tool_result=scrub)

    [assistant] = [m for m in client.calls[1]["messages"] if m["role"] == "assistant"]
    [block] = [b for b in assistant["content"] if b.type == "tool_use"]
    assert block.input == {"expression": "2 + 3"}
