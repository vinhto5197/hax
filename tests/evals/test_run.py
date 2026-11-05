"""The eval runner: run_case drives one case through the agentic harness and
grades it into a result dict; preflight refuses a run against an unmigrated or
unready eval corpus; exit_code turns a run into CI's verdict. The harness,
retrieval and database probes are monkeypatched: no real API or database."""

import asyncio
import uuid
from typing import Any

import anthropic
import httpx2
import pytest
from evals import run
from evals.cases import Case, Expect, Passage
from evals.checks import Check
from evals.judge import JudgeResult, Seen

from apps.api.routers.chat import member_system
from packages.core.rag.retrieval import RetrievedChunk

USER = uuid.UUID("11111111-1111-1111-1111-111111111111")
MODEL = "claude-haiku-4-5"


def _case(
    question: str = "What is my rent?",
    documents: tuple[str, ...] = (),
    note: str | None = None,
    history: tuple[tuple[Any, str], ...] = (),
    expect: Expect | None = None,
    **overrides: Any,
) -> Case:
    fields: dict[str, Any] = {
        "id": "rent",
        "tier": "must",
        "tags": ("rag", "money"),
        "question": question,
        "documents": documents,
        "note": note,
        "history": history,
        # One check by default: a case that checks nothing is an error.
        "expect": expect if expect is not None else Expect(contains_none=("zzz",)),
        "line_hash": "abc123def456",
    }
    fields.update(overrides)
    return Case(**fields)


class FakeJudge:
    def __init__(self, result: JudgeResult | None = None):
        self.result = result or JudgeResult(checks=[], usage=None, error=None)
        self.calls: list[tuple[Any, ...]] = []

    async def grade(
        self,
        question: str,
        answer: str,
        key_points: tuple[str, ...],
        grounded: bool,
        seen: Seen,
    ) -> JudgeResult:
        self.calls.append((question, answer, key_points, grounded, seen))
        return self.result


class FakeStream:
    """Stands in for stream_completion_agentic: records each call, fires the
    scripted callbacks, yields the scripted events, then optionally raises."""

    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        usages: list[dict[str, Any]] | None = None,
        raises: BaseException | None = None,
    ):
        self.events = events if events is not None else [{"content": "ok"}]
        self.tool_results = tool_results or []
        self.usages = usages or []
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        messages,
        system=None,
        model=MODEL,
        *,
        ctx,
        tools=True,
        on_usage=None,
        on_tool_result=None,
    ):
        self.calls.append(
            {"messages": list(messages), "system": system, "model": model, "ctx": ctx}
        )
        for usage in self.usages:
            if on_usage is not None:
                on_usage(usage)
        for result in self.tool_results:
            if on_tool_result is not None:
                on_tool_result(result)
        for event in self.events:
            yield event
        if self.raises is not None:
            raise self.raises


def _usage(input: int, output: int) -> dict[str, Any]:
    return {
        "model": MODEL,
        "input": input,
        "output": output,
        "cache_read": 0,
        "cache_write": 0,
    }


def _tool(name: str, output: str) -> dict[str, Any]:
    return {"name": name, "input": {}, "output": output, "is_error": False}


def _source(excerpt: str) -> dict[str, Any]:
    return {
        "document_id": str(uuid.uuid4()),
        "filename": "lease.md",
        "chunk_idx": 0,
        "excerpt": excerpt,
        "distance": 0.2,
    }


def _chunk(content: str, filename: str, distance: float, idx: int = 0):
    return RetrievedChunk(
        content=content,
        filename=filename,
        distance=distance,
        document_id=uuid.uuid4(),
        chunk_idx=idx,
    )


def _no_retrieve(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("retrieve must not be called")

    monkeypatch.setattr(run, "retrieve", boom)


def _retrieve_returning(monkeypatch, chunks):
    calls: list[tuple[Any, ...]] = []

    async def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return list(chunks)

    monkeypatch.setattr(run, "retrieve", fake)
    return calls


async def test_run_case_collects_answer_tools_and_seen(monkeypatch):
    _no_retrieve(monkeypatch)
    stream = FakeStream(
        events=[
            {"status": "Searching documents"},
            {"content": "Your rent "},
            {"sources": [_source("Rent is 1200"), _source("Due on the 1st")]},
            {"content": "is $1,200."},
        ],
        tool_results=[
            _tool("search_documents", "passage text"),
            _tool("calculator", "1200"),
        ],
    )
    monkeypatch.setattr(run, "stream_completion_agentic", stream)
    judge = FakeJudge(
        JudgeResult(
            checks=[Check("key_point", True, detail="rent is 1200", reason="stated")],
            usage=None,
            error=None,
        )
    )
    case = _case(
        note="I rent in Austin",
        expect=Expect(key_points=("rent is 1200",), grounded=True),
    )

    result = await run.run_case(case, USER, MODEL, judge)

    assert result["id"] == "rent"
    assert result["tier"] == "must"
    assert result["tags"] == ["rag", "money"]
    assert result["question"] == "What is my rent?"
    assert result["answer"] == "Your rent is $1,200."
    assert result["tools_fired"] == ["search_documents", "calculator"]
    assert result["case_hash"] == "abc123def456"
    assert result["seen"] == {
        "passages": ["Rent is 1200", "Due on the 1st"],
        "tool_outputs": ["passage text", "1200"],
        "note": "I rent in Austin",
    }
    assert result["outcome"] == "pass"
    assert result["error"] is None
    assert isinstance(result["seconds"], float) and result["seconds"] >= 0
    assert result["context"]["note"] == "I rent in Austin"
    assert result["context"]["documents"] == []

    call = stream.calls[0]
    assert call["model"] == MODEL
    assert call["ctx"].user_id == USER

    assert len(judge.calls) == 1
    question, answer, key_points, grounded, seen = judge.calls[0]
    assert question == "What is my rent?"
    assert answer == "Your rent is $1,200."
    assert key_points == ("rent is 1200",)
    assert grounded is True
    assert seen == Seen(
        passages=("Rent is 1200", "Due on the 1st"),
        tool_outputs=("passage text", "1200"),
        note="I rent in Austin",
        history=(),
    )


async def test_run_case_passes_the_note_through_member_system(monkeypatch):
    _no_retrieve(monkeypatch)
    stream = FakeStream()
    monkeypatch.setattr(run, "stream_completion_agentic", stream)

    await run.run_case(_case(note="I am vegetarian"), USER, MODEL, FakeJudge())
    await run.run_case(_case(note=None), USER, MODEL, FakeJudge())

    with_note, without_note = stream.calls
    assert with_note["system"] == member_system("I am vegetarian")
    assert "I am vegetarian" in with_note["system"]
    assert without_note["system"] == member_system(None)


async def test_run_case_replays_history_before_the_question(monkeypatch):
    _no_retrieve(monkeypatch)
    stream = FakeStream()
    monkeypatch.setattr(run, "stream_completion_agentic", stream)
    case = _case(
        question="And in euros?",
        history=(("user", "What is my rent?"), ("assistant", "It is $1,200.")),
    )

    await run.run_case(case, USER, MODEL, FakeJudge())

    assert stream.calls[0]["messages"] == [
        {"role": "user", "content": "What is my rent?"},
        {"role": "assistant", "content": "It is $1,200."},
        {"role": "user", "content": "And in euros?"},
    ]


async def test_run_case_records_history_as_pairs(monkeypatch):
    _no_retrieve(monkeypatch)
    monkeypatch.setattr(run, "stream_completion_agentic", FakeStream())
    judge = FakeJudge()
    history = (("user", "What is my rent?"), ("assistant", "It is $1,200."))
    case = _case(history=history, expect=Expect(key_points=("x",)))

    result = await run.run_case(case, USER, MODEL, judge)

    assert result["context"]["history"] == [
        ["user", "What is my rent?"],
        ["assistant", "It is $1,200."],
    ]
    assert judge.calls[0][4].history == history


async def test_run_case_sums_model_tokens(monkeypatch):
    _no_retrieve(monkeypatch)
    stream = FakeStream(usages=[_usage(100, 20), _usage(250, 5), _usage(7, 3)])
    monkeypatch.setattr(run, "stream_completion_agentic", stream)

    result = await run.run_case(_case(), USER, MODEL, FakeJudge())

    assert result["tokens"] == {"in": 357, "out": 28}


async def test_api_error_case_is_error_and_run_continues(monkeypatch):
    _no_retrieve(monkeypatch)
    failing = FakeStream(
        events=[{"content": "partial"}],
        raises=anthropic.APIConnectionError(
            request=httpx2.Request("POST", "https://x")
        ),
    )
    monkeypatch.setattr(run, "stream_completion_agentic", failing)
    judge = FakeJudge()

    result = await run.run_case(_case(), USER, MODEL, judge)

    assert result["outcome"] == "error"
    assert isinstance(result["error"], str) and result["error"]
    assert "APIConnectionError" in result["error"]
    assert judge.calls == []

    monkeypatch.setattr(
        run, "stream_completion_agentic", FakeStream(events=[{"content": "fine"}])
    )
    again = await run.run_case(_case(), USER, MODEL, FakeJudge())
    assert again["outcome"] == "pass"
    assert again["error"] is None
    assert again["answer"] == "fine"


async def test_judge_error_makes_the_case_error(monkeypatch):
    _no_retrieve(monkeypatch)
    monkeypatch.setattr(run, "stream_completion_agentic", FakeStream())
    judge = FakeJudge(
        JudgeResult(checks=[], usage=None, error="judge reply unparseable")
    )
    case = _case(expect=Expect(key_points=("a point",)))

    result = await run.run_case(case, USER, MODEL, judge)

    assert result["outcome"] == "error"
    assert result["error"] == "judge reply unparseable"


async def test_failed_check_makes_the_case_fail(monkeypatch):
    _no_retrieve(monkeypatch)
    stream = FakeStream(
        events=[{"content": "Your rent is $1,200."}],
        tool_results=[_tool("search_documents", "passage")],
    )
    monkeypatch.setattr(run, "stream_completion_agentic", stream)
    judge = FakeJudge(
        JudgeResult(
            checks=[
                Check("key_point", True, detail="rent", reason="stated"),
                Check("grounded", False, reason="invented a date"),
            ],
            usage=None,
            error=None,
        )
    )
    case = _case(
        expect=Expect(
            tools=frozenset({"search_documents"}),
            key_points=("rent",),
            grounded=True,
        )
    )

    result = await run.run_case(case, USER, MODEL, judge)

    assert result["outcome"] == "fail"
    assert result["error"] is None
    assert result["checks"] == [
        {"check": "tools", "pass": True, "detail": None, "reason": None},
        {"check": "key_point", "pass": True, "detail": "rent", "reason": "stated"},
        {
            "check": "grounded",
            "pass": False,
            "detail": None,
            "reason": "invented a date",
        },
    ]


async def test_case_without_checks_is_an_error(monkeypatch):
    # all([]) would pass any answer.
    _no_retrieve(monkeypatch)
    monkeypatch.setattr(run, "stream_completion_agentic", FakeStream())

    result = await run.run_case(_case(expect=Expect()), USER, MODEL, FakeJudge())

    assert result["checks"] == []
    assert result["outcome"] == "error"
    assert result["error"] == "the case names nothing to check"


async def test_retrieval_rank_and_distances_recorded(monkeypatch):
    monkeypatch.setattr(run, "stream_completion_agentic", FakeStream())
    calls = _retrieve_returning(
        monkeypatch,
        [
            _chunk("The RENT is due monthly", "notes.md", 0.11),
            _chunk("Clause 4: The Rent Is $1,200 a month", "lease.md", 0.23, 4),
            _chunk("the rent is also mentioned here", "lease.md", 0.31, 9),
        ],
    )
    case = _case(
        documents=("lease.md", "notes.md"),
        expect=Expect(passage=Passage(document="lease.md", contains="rent is $1,200")),
    )

    result = await run.run_case(case, USER, MODEL, FakeJudge())

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert list(args) + list(kwargs.values()) == ["What is my rent?", USER]
    assert result["retrieval"] == {
        "nearest_distance": 0.11,
        "expected_passage_rank": 2,
        "distance": 0.23,
    }
    assert result["context"]["documents"] == ["lease.md", "notes.md"]


async def test_retrieval_miss_records_no_rank(monkeypatch):
    monkeypatch.setattr(run, "stream_completion_agentic", FakeStream())
    _retrieve_returning(
        monkeypatch,
        [
            _chunk("Parking is extra", "lease.md", 0.4),
            _chunk("rent is $1,200", "notes.md", 0.5),
        ],
    )
    case = _case(
        documents=("lease.md",),
        expect=Expect(passage=Passage(document="lease.md", contains="rent is $1,200")),
    )

    result = await run.run_case(case, USER, MODEL, FakeJudge())

    assert result["retrieval"] == {
        "nearest_distance": 0.4,
        "expected_passage_rank": None,
        "distance": None,
    }


async def test_case_without_documents_skips_retrieval(monkeypatch):
    _no_retrieve(monkeypatch)
    monkeypatch.setattr(run, "stream_completion_agentic", FakeStream())

    result = await run.run_case(_case(documents=()), USER, MODEL, FakeJudge())

    assert result["retrieval"] is None


def _probes(monkeypatch, *, head=True, statuses=("ready",), chunks=None):
    calls: dict[str, list[Any]] = {"at_head": [], "statuses": [], "retrieve": []}

    async def at_head():
        calls["at_head"].append(())
        return head

    async def document_statuses(owner):
        calls["statuses"].append(owner)
        return list(statuses)

    async def retrieve(query, user_id, *args, **kwargs):
        calls["retrieve"].append((query, user_id))
        if chunks is None:
            return [_chunk("some text", "lease.md", 0.2)]
        return list(chunks)

    monkeypatch.setattr(run, "at_head", at_head)
    monkeypatch.setattr(run, "document_statuses", document_statuses)
    monkeypatch.setattr(run, "retrieve", retrieve)
    return calls


async def test_preflight_passes_when_ready(monkeypatch):
    calls = _probes(monkeypatch, statuses=("ready", "ready"))

    assert await run.preflight(USER, "rent") is None
    assert calls["statuses"] == [USER]
    assert calls["retrieve"] == [("rent", USER)]


async def test_preflight_reports_unmigrated_database(monkeypatch):
    calls = _probes(monkeypatch, head=False)

    reason = await run.preflight(USER, "rent")

    assert reason and "migrat" in reason.lower()
    assert calls["retrieve"] == []


async def test_preflight_reports_no_documents(monkeypatch):
    calls = _probes(monkeypatch, statuses=())

    reason = await run.preflight(USER, "rent")

    assert reason and "no documents" in reason.lower()
    assert calls["retrieve"] == []


async def test_preflight_reports_unready_corpus(monkeypatch):
    calls = _probes(monkeypatch, statuses=("ready", "processing", "pending"))

    reason = await run.preflight(USER, "rent")

    assert reason and "not ready" in reason.lower()
    assert "2" in reason
    assert calls["retrieve"] == []


async def test_preflight_reports_empty_retrieval(monkeypatch):
    _probes(monkeypatch, chunks=[])

    reason = await run.preflight(USER, "rent")

    assert reason and "retriev" in reason.lower()


def _result(tier: str, outcome: str) -> dict[str, Any]:
    return {"id": f"{tier}-{outcome}", "tier": tier, "outcome": outcome}


@pytest.mark.parametrize(
    ("cases", "code"),
    [
        ([_result("must", "pass"), _result("probe", "pass")], 0),
        ([_result("must", "pass"), _result("must", "fail")], 1),
        ([_result("must", "pass"), _result("probe", "fail")], 0),
        ([_result("must", "pass"), _result("must", "error")], 1),
        ([_result("must", "pass"), _result("probe", "error")], 1),
    ],
    ids=["all-pass", "must-fail", "probe-fail", "must-error", "probe-error"],
)
def test_exit_codes(cases, code):
    assert run.exit_code(cases) == code


def test_stack_problem_refuses_anything_but_the_eval_stack():
    local = "http://localhost:9000"
    assert run.stack_problem("hax_eval", "hax-eval", local) is None
    assert run.stack_problem("hax_eval", "hax-eval", "http://127.0.0.1:9000") is None
    assert "make eval" in (run.stack_problem("hax", "hax-eval", local) or "")
    assert "make eval" in (run.stack_problem("hax_eval", "hax-documents", local) or "")
    assert run.stack_problem(None, "hax-eval", local) is not None
    # An unset endpoint is real AWS S3; any other host is not the stand-in.
    assert run.stack_problem("hax_eval", "hax-eval", None) is not None
    assert (
        run.stack_problem("hax_eval", "hax-eval", "https://s3.amazonaws.com")
        is not None
    )


def _start_from(monkeypatch, tmp_path, lines: list[str]):
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(line + "\n" for line in lines))
    monkeypatch.setenv("EVAL_CASES", str(cases))
    monkeypatch.setattr(run, "stack_problem", lambda *stack: None)


def test_dev_stack_exits_2_before_anything_runs(monkeypatch, capsys):
    monkeypatch.setattr(run, "load_cases", lambda path: pytest.fail("loaded"))

    assert run._evaluate() == 2
    assert "make eval" in capsys.readouterr().err


def test_missing_case_file_exits_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("EVAL_CASES", str(tmp_path / "nope.jsonl"))
    monkeypatch.setattr(run, "stack_problem", lambda *stack: None)

    assert run._evaluate() == 2
    assert "nope.jsonl" in capsys.readouterr().err


def test_empty_case_file_exits_2(monkeypatch, tmp_path, capsys):
    _start_from(monkeypatch, tmp_path, [])

    assert run._evaluate() == 2
    assert "no cases" in capsys.readouterr().err


def test_setup_failure_exits_2(monkeypatch, tmp_path, capsys):
    _start_from(monkeypatch, tmp_path, ['{"id": "a", "question": "q"}'])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def voyage_down():
        # Not an OSError: the outer handler must not be what catches it.
        raise ValueError("voyage unreachable")

    monkeypatch.setattr(run, "setup_users", voyage_down)

    assert run._evaluate() == 2
    assert "voyage unreachable" in capsys.readouterr().err


OWNER = uuid.UUID("22222222-2222-2222-2222-222222222222")
EMPTY = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _cases(n: int, documents: tuple[str, ...] = ("lease.md",)) -> list[Case]:
    return [_case(id=f"case-{i}", documents=documents) for i in range(n)]


def _fake_run_case(monkeypatch, delay=lambda case: 0.01):
    """Patches run.run_case with a fake that records its calls and tracks how
    many are in flight at once."""
    state: dict[str, Any] = {"in_flight": 0, "max": 0, "calls": [], "log": []}

    async def fake(case, user_id, model, judge):
        state["calls"].append((case.id, user_id, model, judge))
        state["in_flight"] += 1
        state["max"] = max(state["max"], state["in_flight"])
        state["log"].append(("start", case.id))
        try:
            await asyncio.sleep(delay(case))
        finally:
            state["in_flight"] -= 1
            state["log"].append(("end", case.id))
        return {"id": case.id, "outcome": "pass", "tier": case.tier}

    monkeypatch.setattr(run, "run_case", fake)
    return state


def test_concurrency_default_is_a_positive_int():
    assert isinstance(run.CONCURRENCY, int)
    assert run.CONCURRENCY >= 1


async def test_run_cases_keeps_case_order_when_calls_finish_out_of_order(
    monkeypatch,
):
    cases = _cases(5)
    index = {case.id: i for i, case in enumerate(cases)}
    state = _fake_run_case(
        monkeypatch, delay=lambda case: 0.01 * (len(cases) - index[case.id])
    )

    results = await run.run_cases(cases, OWNER, EMPTY, MODEL, FakeJudge(), 5)

    assert [result["id"] for result in results] == [case.id for case in cases]
    finished = [case_id for kind, case_id in state["log"] if kind == "end"]
    assert finished != [case.id for case in cases]
    assert len(state["calls"]) == len(cases)


async def test_run_cases_never_exceeds_the_concurrency(monkeypatch):
    cases = _cases(7)
    state = _fake_run_case(monkeypatch, delay=lambda case: 0.02)

    results = await run.run_cases(cases, OWNER, EMPTY, MODEL, FakeJudge(), 3)

    assert state["max"] == 3
    assert state["in_flight"] == 0
    assert sorted(call[0] for call in state["calls"]) == sorted(c.id for c in cases)
    assert len(state["calls"]) == 7
    assert [result["id"] for result in results] == [case.id for case in cases]


async def test_run_cases_with_concurrency_one_runs_one_at_a_time(monkeypatch):
    cases = _cases(4)
    state = _fake_run_case(monkeypatch, delay=lambda case: 0.005)

    results = await run.run_cases(cases, OWNER, EMPTY, MODEL, FakeJudge(), 1)

    assert state["max"] == 1
    kinds = [kind for kind, _ in state["log"]]
    assert kinds == ["start", "end"] * len(cases)
    for start, end in zip(state["log"][::2], state["log"][1::2], strict=True):
        assert start[1] == end[1]
    assert [result["id"] for result in results] == [case.id for case in cases]


async def test_run_cases_routes_cases_without_documents_to_the_empty_member(
    monkeypatch,
):
    cases = [
        _case(id="with-docs", documents=("lease.md",)),
        _case(id="no-docs", documents=()),
        _case(id="more-docs", documents=("lease.md", "notes.md")),
        _case(id="also-none", documents=()),
    ]
    state = _fake_run_case(monkeypatch, delay=lambda case: 0)
    judge = FakeJudge()

    results = await run.run_cases(cases, OWNER, EMPTY, MODEL, judge, 2)

    users = {case_id: user_id for case_id, user_id, _, _ in state["calls"]}
    assert users == {
        "with-docs": OWNER,
        "no-docs": EMPTY,
        "more-docs": OWNER,
        "also-none": EMPTY,
    }
    assert all(model == MODEL for _, _, model, _ in state["calls"])
    assert all(passed is judge for _, _, _, passed in state["calls"])
    assert [result["id"] for result in results] == [case.id for case in cases]


@pytest.mark.parametrize("value", ["0", "-2", "abc", "1.5"])
def test_bad_concurrency_exits_2_before_any_case(monkeypatch, tmp_path, capsys, value):
    # 0 would admit no case: the run would hang with the eval lock held.
    _start_from(monkeypatch, tmp_path, ['{"id": "a", "question": "q"}'])
    monkeypatch.setenv("EVAL_CONCURRENCY", value)
    monkeypatch.setattr(run, "_run_and_close", lambda *a: pytest.fail("started"))

    assert run._evaluate() == 2
    assert "EVAL_CONCURRENCY" in capsys.readouterr().err


def test_concurrency_reads_the_environment(monkeypatch):
    monkeypatch.delenv("EVAL_CONCURRENCY", raising=False)
    assert run.concurrency() == run.CONCURRENCY
    monkeypatch.setenv("EVAL_CONCURRENCY", "2")
    assert run.concurrency() == 2


# ── Storage and retrieval guards ─────────────────────────────────────────────


def test_storage_outside_the_stand_in_exits_2_before_any_case(monkeypatch, capsys):
    # An unset endpoint is real AWS S3: the run must refuse, not ingest there.
    from types import SimpleNamespace

    monkeypatch.setattr(
        run, "engine", SimpleNamespace(url=SimpleNamespace(database="hax_eval"))
    )
    monkeypatch.setattr(run.storage, "S3_BUCKET", "hax-eval")
    monkeypatch.setattr(run.storage, "_ENDPOINT_URL", None)
    monkeypatch.setattr(run, "load_cases", lambda path: pytest.fail("loaded"))

    assert run._evaluate() == 2
    assert "AWS" in capsys.readouterr().err


def test_dev_bucket_exits_2_before_any_case(monkeypatch, capsys):
    from types import SimpleNamespace

    monkeypatch.setattr(
        run, "engine", SimpleNamespace(url=SimpleNamespace(database="hax_eval"))
    )
    monkeypatch.setattr(run.storage, "S3_BUCKET", "hax-documents")
    monkeypatch.setattr(run.storage, "_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setattr(run, "load_cases", lambda path: pytest.fail("loaded"))

    assert run._evaluate() == 2
    assert "hax-documents" in capsys.readouterr().err


def test_make_eval_pins_the_stack_the_runner_requires():
    from pathlib import Path

    makefile = (Path(run.ROOT) / "Makefile").read_text()
    env = makefile[makefile.index("EVAL_ENV :=") : makefile.index(".PHONY: eval")]
    assert f"localhost:5432/{run.EVAL_DATABASE}" in env
    assert f"S3_BUCKET={run.EVAL_BUCKET}" in env
    assert "S3_ENDPOINT_URL=http://localhost:9000" in env
    for key in ("S3_REGION=", "S3_ACCESS_KEY_ID=", "S3_SECRET_ACCESS_KEY="):
        assert key in env, key


async def test_empty_search_for_the_corpus_owner_is_a_stack_error(monkeypatch):
    # retrieve() turns any fault into "nothing found"; with no cutoff the
    # owner always has passages, so it is the stack failing, not the model.
    _retrieve_returning(monkeypatch, [_chunk("Rent is 1200", "lease.md", 0.3)])
    stream = FakeStream(
        tool_results=[_tool("search_documents", run.NO_PASSAGES + " in the documents.")]
    )
    monkeypatch.setattr(run, "stream_completion_agentic", stream)

    result = await run.run_case(
        _case(documents=("lease.md",)), USER, MODEL, FakeJudge()
    )

    assert result["outcome"] == "error"
    assert "stack fault" in result["error"]


async def test_empty_retrieval_score_for_the_corpus_owner_is_a_stack_error(monkeypatch):
    _retrieve_returning(monkeypatch, [])
    monkeypatch.setattr(run, "stream_completion_agentic", FakeStream())

    result = await run.run_case(
        _case(documents=("lease.md",)), USER, MODEL, FakeJudge()
    )

    assert result["outcome"] == "error"
    assert "stack fault" in result["error"]


async def test_empty_search_under_a_cutoff_is_not_a_stack_error(monkeypatch):
    monkeypatch.setattr(run.retrieval, "MAX_DISTANCE", 0.5)
    _retrieve_returning(monkeypatch, [])
    stream = FakeStream(tool_results=[_tool("search_documents", run.NO_PASSAGES + ".")])
    monkeypatch.setattr(run, "stream_completion_agentic", stream)

    result = await run.run_case(
        _case(documents=("lease.md",)), USER, MODEL, FakeJudge()
    )

    assert result["outcome"] == "pass"


async def test_no_passages_matches_what_the_search_tool_says(monkeypatch):
    from packages.core.agent import tools

    async def nothing(query, user_id):
        return []

    monkeypatch.setattr(tools, "retrieve", nothing)
    out = await tools._run_search_documents(
        tools.SearchDocumentsInput(query="q"), tools.ToolContext(user_id=USER)
    )

    assert isinstance(out, str) and out.startswith(run.NO_PASSAGES)


async def test_each_concurrent_case_runs_as_its_own_member(monkeypatch):
    # The RLS identity a case's model calls and retrieval run under is its
    # own member's, even with cases from both members in flight together.
    from packages.db.user_context import current_user_id

    seen: list[tuple[str, Any, Any]] = []

    async def stream(
        messages,
        system=None,
        model=MODEL,
        *,
        ctx,
        tools=True,
        on_usage=None,
        on_tool_result=None,
    ):
        await asyncio.sleep(0.01)
        seen.append(("stream", ctx.user_id, current_user_id.get()))
        yield {"content": "ok"}

    async def fake_retrieve(query, user_id):
        await asyncio.sleep(0.01)
        seen.append(("retrieve", user_id, current_user_id.get()))
        return [_chunk("text", "lease.md", 0.3)]

    monkeypatch.setattr(run, "stream_completion_agentic", stream)
    monkeypatch.setattr(run, "retrieve", fake_retrieve)
    cases = [
        _case(id=f"c{i}", documents=("lease.md",) if i % 2 else ()) for i in range(6)
    ]

    await run.run_cases(cases, OWNER, EMPTY, MODEL, FakeJudge(), 3)

    assert len(seen) == 6 + 3  # every stream, and the owner cases' retrieval
    assert all(asked == bound for _, asked, bound in seen)
    assert {asked for _, asked, _ in seen} == {OWNER, EMPTY}
    assert current_user_id.get() is None


async def test_a_rejected_search_call_is_graded_not_a_stack_error(monkeypatch):
    _retrieve_returning(monkeypatch, [_chunk("Rent is 1200", "lease.md", 0.3)])
    bad_call = {
        "name": "search_documents",
        "input": {},
        "output": "Invalid input",
        "is_error": True,
    }
    stream = FakeStream(
        tool_results=[bad_call, _tool("search_documents", "[1] Rent is 1200")]
    )
    monkeypatch.setattr(run, "stream_completion_agentic", stream)

    result = await run.run_case(
        _case(documents=("lease.md",)), USER, MODEL, FakeJudge()
    )

    assert result["outcome"] == "pass"
    assert result["error"] is None
