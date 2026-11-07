"""Narration: text the model streams in a call that ends in a tool call still
streams live, then the harness withdraws it with {"retract": <exactly the text
that call yielded as content, separator included>} before the tool's status.
Applying each retract (removing its text from the end of the content so far)
leaves only answers; the model still sees its own narration. Scripted fake
client; no network."""

from packages.core.agent import harness, tools
from tests.core.fake_anthropic import FakeClient, collect, text_block, tool_use

MODEL = "claude-test-model"
CALC = {"expression": "2 + 3"}


def narrated_tool_turn(narration, id_="tu_1"):
    if isinstance(narration, str):
        pieces = [narration] if narration else []
    else:
        pieces = list(narration)
    text = "".join(pieces)
    content = ([text_block(text)] if text else []) + [tool_use("calculator", CALC, id_)]
    return {"text": pieces, "content": content, "stop_reason": "tool_use"}


def answer_turn(text="It is 5."):
    return {"text": [text], "content": [text_block(text)], "stop_reason": "end_turn"}


async def _run(monkeypatch, ctx, turns):
    client = FakeClient(turns)
    monkeypatch.setattr(harness, "_client", client)
    events = await collect(
        harness.stream_completion_agentic(
            [{"role": "user", "content": "what is 2 + 3?"}], model=MODEL, ctx=ctx
        )
    )
    return events, client


def applied(events) -> str:
    """The content a listener keeps: each retract removes its text from the
    end of what has accumulated when it arrives."""
    shown = ""
    for e in events:
        if "content" in e:
            shown += e["content"]
        elif "retract" in e:
            assert shown.endswith(e["retract"]), (shown, e["retract"])
            shown = shown[: len(shown) - len(e["retract"])]
    return shown


def retracts(events) -> list[str]:
    return [e["retract"] for e in events if "retract" in e]


def calc_status() -> dict:
    return {"status": tools.TOOLS["calculator"].label}


def _text_of_block(block) -> str | None:
    if isinstance(block, dict):
        return block.get("text") if block.get("type") == "text" else None
    if getattr(block, "type", None) == "text":
        return getattr(block, "text", None)
    return None


async def test_a_narrated_tool_step_yields_a_retract_of_its_text_after_its_content_and_before_the_status(  # noqa: E501 — the name is the behaviour line
    monkeypatch, ctx
):
    events, _ = await _run(
        monkeypatch, ctx, [narrated_tool_turn("I'll check."), answer_turn()]
    )

    content_i = events.index({"content": "I'll check."})
    retract_i = events.index({"retract": "I'll check."})
    status_i = events.index(calc_status())
    assert content_i < retract_i < status_i
    assert retracts(events) == ["I'll check."]


async def test_after_a_retract_the_next_steps_answer_has_no_leading_separator(
    monkeypatch, ctx
):
    events, _ = await _run(
        monkeypatch, ctx, [narrated_tool_turn("I'll check."), answer_turn("It is 5.")]
    )

    assert applied(events) == "It is 5."
    after_retract = events[events.index({"retract": "I'll check."}) + 1 :]
    assert "".join(e["content"] for e in after_retract if "content" in e) == "It is 5."


async def test_two_narrated_tool_steps_each_retract_their_own_text_and_leave_only_the_answer(  # noqa: E501 — the name is the behaviour line
    monkeypatch, ctx
):
    events, _ = await _run(
        monkeypatch,
        ctx,
        [
            narrated_tool_turn(["Let me ", "add that."], id_="tu_1"),
            narrated_tool_turn("Checking once more.", id_="tu_2"),
            answer_turn("It is 5."),
        ],
    )

    got = retracts(events)
    assert len(got) == 2
    # Nothing is left shown after the first retract, so the second step's
    # text gets no separator.
    assert got == ["Let me add that.", "Checking once more."]
    assert applied(events) == "It is 5."


async def test_each_retract_carries_exactly_what_its_step_yielded_as_content(
    monkeypatch, ctx
):
    events, _ = await _run(
        monkeypatch,
        ctx,
        [
            narrated_tool_turn("", id_="tu_0"),
            narrated_tool_turn(["One ", "moment."], id_="tu_1"),
            narrated_tool_turn("Again.", id_="tu_2"),
            answer_turn("It is 5."),
        ],
    )

    step_text = ""
    seen = 0
    for e in events:
        if "content" in e:
            step_text += e["content"]
        elif "retract" in e:
            assert e["retract"] == step_text
            seen += 1
            step_text = ""
        else:
            step_text = ""
    assert seen == 2
    assert applied(events) == "It is 5."


async def test_a_tool_step_with_no_text_yields_no_retract(monkeypatch, ctx):
    events, _ = await _run(
        monkeypatch, ctx, [narrated_tool_turn(""), answer_turn("It is 5.")]
    )

    assert retracts(events) == []
    assert calc_status() in events
    assert applied(events) == "It is 5."


async def test_a_plain_answer_yields_no_retract_and_its_content_in_full(
    monkeypatch, ctx
):
    events, _ = await _run(monkeypatch, ctx, [answer_turn("Hello there.")])

    assert events == [{"content": "Hello there."}]


async def test_the_model_still_sees_its_own_narration_in_the_next_call(
    monkeypatch, ctx
):
    _, client = await _run(
        monkeypatch, ctx, [narrated_tool_turn("I'll check."), answer_turn()]
    )

    second = client.calls[1]["messages"]
    assistant_texts = [
        _text_of_block(block)
        for m in second
        if m["role"] == "assistant" and not isinstance(m["content"], str)
        for block in m["content"]
    ]
    assert "I'll check." in assistant_texts
