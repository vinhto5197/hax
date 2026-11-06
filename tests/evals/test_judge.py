"""The model judge: check_verdict turns the judge's tool-call input into
Checks in key-point order (or an error string, never a raise); AnthropicJudge
grades one answer against what the model under test was shown, retries a
reply with no usable verdict once, and reports summed usage. No real API is
called."""

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from evals.checks import Check
from evals.judge import (
    DEFAULT_JUDGE_MODEL,
    AnthropicJudge,
    JudgeResult,
    Seen,
    check_verdict,
)

POINTS = ("Paris is the capital", "Population is about 2 million")


def _verdict(
    points: list[dict[str, Any]], grounded: dict[str, Any] | None = None
) -> str:
    body: dict[str, Any] = {"points": points}
    if grounded is not None:
        body["grounded"] = grounded
    return json.dumps(body)


def _good_reply() -> str:
    return _verdict(
        [
            {"index": 1, "pass": True, "reason": "stated"},
            {"index": 2, "pass": False, "reason": "missing"},
        ],
        {"pass": True, "reason": "all from passages"},
    )


def _seen(**overrides: Any) -> Seen:
    fields: dict[str, Any] = {
        "passages": (),
        "tool_outputs": (),
        "note": None,
        "history": (),
    }
    fields.update(overrides)
    return Seen(**fields)


def _usage(
    input_tokens: int = 10,
    output_tokens: int = 5,
    cache_read: int | None = 0,
    cache_write: int | None = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


def _resp(text: str, usage: SimpleNamespace | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=usage or _usage(),
    )


def _tool_resp(verdict: str, usage: SimpleNamespace | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use", name="record_verdict", input=json.loads(verdict)
            )
        ],
        usage=usage or _usage(),
    )


class FakeClient:
    def __init__(self, *replies: Any) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        reply = self._replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def _user_text(call: dict[str, Any]) -> str:
    messages = call["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert isinstance(content, str)
    return content


# check_verdict


def test_parse_valid_verdict():
    checks = check_verdict(json.loads(_good_reply()), POINTS, True)

    assert checks == [
        Check("key_point", True, POINTS[0], "stated"),
        Check("key_point", False, POINTS[1], "missing"),
        Check("grounded", True, None, "all from passages"),
    ]


def test_parse_missing_point_is_error():
    text = _verdict(
        [{"index": 1, "pass": True, "reason": "stated"}],
        {"pass": True, "reason": "ok"},
    )

    result = check_verdict(json.loads(text), POINTS, True)

    assert isinstance(result, str) and result


def test_parse_ignores_extra_points():
    text = _verdict(
        [
            {"index": 0, "pass": False, "reason": "zero"},
            {"index": 1, "pass": True, "reason": "first"},
            {"index": 1, "pass": True, "reason": "agreeing duplicate"},
            {"index": 2, "pass": True, "reason": "second"},
            {"index": 3, "pass": False, "reason": "beyond"},
        ]
    )

    checks = check_verdict(json.loads(text), POINTS, False)

    assert checks == [
        Check("key_point", True, POINTS[0], "first"),
        Check("key_point", True, POINTS[1], "second"),
    ]


def test_parse_conflicting_duplicate_point_is_error():
    text = _verdict(
        [
            {"index": 1, "pass": True, "reason": "yes"},
            {"index": 1, "pass": False, "reason": "no"},
            {"index": 2, "pass": True, "reason": "second"},
        ]
    )

    result = check_verdict(json.loads(text), POINTS, False)

    assert isinstance(result, str) and result


@pytest.mark.parametrize("points", [5, True, "1", {"index": 1}])
def test_parse_points_not_a_list_is_error(points):
    result = check_verdict({"points": points}, POINTS, False)

    assert isinstance(result, str) and result


def test_missing_api_key_refused_at_construction(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicJudge(model="m")


def test_parse_out_of_order_points():
    text = _verdict(
        [
            {"index": 2, "pass": False, "reason": "second"},
            {"index": 1, "pass": True, "reason": "first"},
        ],
        {"pass": False, "reason": "made up"},
    )

    checks = check_verdict(json.loads(text), POINTS, True)

    assert checks == [
        Check("key_point", True, POINTS[0], "first"),
        Check("key_point", False, POINTS[1], "second"),
        Check("grounded", False, None, "made up"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "[]",
        _verdict(
            [
                {"index": 1, "pass": "yes", "reason": "stated"},
                {"index": 2, "pass": True, "reason": "stated"},
            ]
        ),
        _verdict(
            [
                {"index": 1, "pass": True},
                {"index": 2, "pass": True, "reason": "stated"},
            ]
        ),
    ],
    ids=["array", "pass-not-bool", "missing-reason"],
)
def test_parse_garbage_is_error(text: str):
    result = check_verdict(json.loads(text), POINTS, False)

    assert isinstance(result, str) and result


@pytest.mark.parametrize(
    "grounded",
    [None, {"pass": "yes", "reason": "ok"}, {"pass": True}],
    ids=["absent", "pass-not-bool", "missing-reason"],
)
def test_parse_missing_grounded_is_error_when_asked(grounded: dict[str, Any] | None):
    text = _verdict(
        [
            {"index": 1, "pass": True, "reason": "a"},
            {"index": 2, "pass": True, "reason": "b"},
        ],
        grounded,
    )

    result = check_verdict(json.loads(text), POINTS, True)

    assert isinstance(result, str) and result


def test_parse_ignores_grounded_when_not_asked():
    text = _good_reply()

    checks = check_verdict(json.loads(text), POINTS, False)

    assert isinstance(checks, list)
    assert [c.check for c in checks] == ["key_point", "key_point"]


def test_parse_grounded_only():
    text = _verdict([], {"pass": False, "reason": "unsupported claim"})

    checks = check_verdict(json.loads(text), (), True)

    assert checks == [Check("grounded", False, None, "unsupported claim")]


# AnthropicJudge.grade


async def test_grade_skips_the_call_when_nothing_to_judge():
    client = FakeClient()
    judge = AnthropicJudge(model="m", client=client)

    result = await judge.grade("q", "a", (), False, _seen())

    assert result == JudgeResult(checks=[], usage=None, error=None)
    assert client.calls == []


async def test_grade_retries_once_then_errors():
    client = FakeClient(
        _resp("garbage", _usage(100, 20, 3, 4)),
        _resp("still garbage", _usage(50, 10, 1, 2)),
    )
    judge = AnthropicJudge(model="m", client=client)

    result = await judge.grade("q", "a", POINTS, True, _seen())

    assert len(client.calls) == 2
    assert result.checks == []
    assert result.error is not None
    assert result.error.startswith("judge reply unparseable")
    assert "reply began" in result.error  # the cause travels with the error
    assert result.usage == {
        "model": "m",
        "input": 150,
        "output": 30,
        "cache_read": 4,
        "cache_write": 6,
    }


async def test_grade_tool_call_rejected_twice_errors_with_the_reason():
    missing_point = _verdict(
        [{"index": 1, "pass": True, "reason": "stated"}],
        {"pass": True, "reason": "ok"},
    )
    client = FakeClient(_tool_resp(missing_point), _tool_resp(missing_point))
    judge = AnthropicJudge(model="m", client=client)

    result = await judge.grade("q", "a", POINTS, True, _seen())

    assert len(client.calls) == 2
    assert result.checks == []
    assert result.error is not None
    assert result.error.startswith("judge reply unparseable")
    reason = check_verdict(json.loads(missing_point), POINTS, True)
    assert isinstance(reason, str) and reason in result.error


async def test_grade_retry_that_parses_succeeds():
    client = FakeClient(
        _resp("garbage", _usage(100, 20)),
        _tool_resp(_good_reply(), _usage(50, 10)),
    )
    judge = AnthropicJudge(model="m", client=client)

    result = await judge.grade("q", "a", POINTS, True, _seen())

    assert len(client.calls) == 2
    assert result.error is None
    assert result.checks == [
        Check("key_point", True, POINTS[0], "stated"),
        Check("key_point", False, POINTS[1], "missing"),
        Check("grounded", True, None, "all from passages"),
    ]
    assert result.usage is not None
    assert result.usage["input"] == 150
    assert result.usage["output"] == 30


@pytest.mark.parametrize("fail_on", [1, 2], ids=["first-call", "retry"])
async def test_grade_api_error_is_error_not_raised(fail_on: int):
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x"))
    replies: list[Any] = [error] if fail_on == 1 else [_resp("garbage"), error]
    client = FakeClient(*replies)
    judge = AnthropicJudge(model="m", client=client)

    result = await judge.grade("q", "a", POINTS, False, _seen())

    assert result.checks == []
    assert isinstance(result.error, str)
    assert result.error.startswith("judge API error")
    if fail_on == 1:
        assert result.usage is None
    else:
        # The first call's tokens were spent and are still counted.
        assert result.usage is not None and result.usage["input"] > 0


async def test_prompt_carries_seen():
    # A search's passages reach the model inside its tool output, so the
    # judge reads them there; seen.passages is not sent a second time.
    seen = _seen(
        passages=("PASSAGE-ALPHA text",),
        tool_outputs=("TOOL-OUT-ONE [1] PASSAGE-ALPHA text", "TOOL-OUT-TWO"),
        note="NOTE-I-am-a-baker",
        history=(("user", "HIST-USER-turn"), ("assistant", "HIST-ASSISTANT-turn")),
    )
    client = FakeClient(_tool_resp(_good_reply()))
    judge = AnthropicJudge(model="m", client=client)

    await judge.grade("QUESTION-what-city", "ANSWER-paris", POINTS, True, seen)

    assert len(client.calls) == 1
    text = _user_text(client.calls[0])
    for needle in (
        "QUESTION-what-city",
        "ANSWER-paris",
        *POINTS,
        "TOOL-OUT-ONE",
        "TOOL-OUT-TWO",
        "NOTE-I-am-a-baker",
        "HIST-USER-turn",
        "HIST-ASSISTANT-turn",
    ):
        assert needle in text, needle
    assert text.count("PASSAGE-ALPHA text") == 1  # once, inside the tool output


async def test_grade_reports_usage():
    client = FakeClient(_tool_resp(_good_reply(), _usage(120, 40, None, None)))
    judge = AnthropicJudge(model="judge-model", client=client)

    result = await judge.grade("q", "a", POINTS, True, _seen())

    assert result.error is None
    assert result.usage == {
        "model": "judge-model",
        "input": 120,
        "output": 40,
        "cache_read": 0,
        "cache_write": 0,
    }


async def test_grade_uses_the_given_model():
    client = FakeClient(_resp("garbage"), _tool_resp(_good_reply()))
    judge = AnthropicJudge(model="m", client=client)

    await judge.grade("q", "a", POINTS, False, _seen())

    assert len(client.calls) == 2
    assert all(call["model"] == "m" for call in client.calls)


async def test_truncated_reply_is_error_without_retry():
    resp = _resp('{"points": [{"index": 1, "pass": tr')
    resp.stop_reason = "max_tokens"
    client = FakeClient(resp, _tool_resp(_good_reply()))
    judge = AnthropicJudge(model="m", client=client)

    result = await judge.grade("q", "a", POINTS, False, _seen())

    assert result.error == "judge reply truncated"
    assert result.checks == []
    assert len(client.calls) == 1


async def test_judge_model_read_from_env_at_construction(monkeypatch):
    monkeypatch.setenv("JUDGE_MODEL", "env-model")
    client = FakeClient(_tool_resp(_good_reply()))

    await AnthropicJudge(client=client).grade("q", "a", POINTS, False, _seen())

    assert client.calls[0]["model"] == "env-model"


async def test_empty_judge_model_env_falls_back_to_the_default(monkeypatch):
    # make eval passes JUDGE_MODEL= when it is not on its command line.
    monkeypatch.setenv("JUDGE_MODEL", "")
    client = FakeClient(_tool_resp(_good_reply()))

    await AnthropicJudge(client=client).grade("q", "a", POINTS, False, _seen())

    assert client.calls[0]["model"] == DEFAULT_JUDGE_MODEL


async def test_verdict_comes_back_as_a_forced_tool_call():
    verdict = json.loads(_good_reply())
    resp = SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", name="record_verdict", input=verdict)
        ],
        usage=_usage(),
    )
    client = FakeClient(resp)

    result = await AnthropicJudge(model="m", client=client).grade(
        "q", "a", POINTS, True, _seen()
    )

    assert result.error is None
    assert [c.passed for c in result.checks] == [True, False, True]
    call = client.calls[0]
    assert call["tool_choice"] == {
        "type": "tool",
        "name": "record_verdict",
        "disable_parallel_tool_use": True,
    }
    assert [t["name"] for t in call["tools"]] == ["record_verdict"]


async def test_tool_verdict_with_backticks_in_a_reason_still_parses():
    verdict = json.loads(_good_reply())
    verdict["points"][0]["reason"] = "It quotes ```json {} ``` and still states it."
    resp = SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", name="record_verdict", input=verdict)
        ],
        usage=_usage(),
    )

    result = await AnthropicJudge(model="m", client=FakeClient(resp)).grade(
        "q", "a", POINTS, True, _seen()
    )

    assert result.error is None
    assert [c.passed for c in result.checks] == [True, False, True]


async def test_refusal_is_an_error_without_retry():
    resp = _resp("")
    resp.stop_reason = "refusal"
    client = FakeClient(resp, _tool_resp(_good_reply()))

    result = await AnthropicJudge(model="m", client=client).grade(
        "q", "a", POINTS, False, _seen()
    )

    assert result.error == "judge refused to grade"
    assert len(client.calls) == 1


async def test_a_verdict_sent_as_a_json_string_is_read():
    verdict = json.loads(_good_reply())
    verdict["grounded"] = json.dumps(verdict["grounded"])
    resp = SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", name="record_verdict", input=verdict)
        ],
        usage=_usage(),
    )

    result = await AnthropicJudge(model="m", client=FakeClient(resp)).grade(
        "q", "a", POINTS, True, _seen()
    )

    assert result.error is None
    assert result.checks[-1].check == "grounded" and result.checks[-1].passed is True
