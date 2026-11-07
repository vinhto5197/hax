"""The eval grades what the user would be left with: a {"retract": text}
event removes that text from the end of the answer run_case collects, so
narration never reaches the code checks or the judge. The harness and
retrieval are monkeypatched: no real API or database."""

from evals import run
from evals.cases import Expect
from evals.checks import Check
from evals.judge import JudgeResult

from tests.evals.test_run import MODEL, USER, FakeJudge, FakeStream, _case, _no_retrieve


async def test_run_case_drops_retracted_narration_from_the_graded_answer(monkeypatch):
    _no_retrieve(monkeypatch)
    stream = FakeStream(
        events=[
            {"content": "Let me look."},
            {"retract": "Let me look."},
            {"status": "Searching documents"},
            {"content": "Your rent is $1,200."},
        ]
    )
    monkeypatch.setattr(run, "stream_completion_agentic", stream)
    judge = FakeJudge(
        JudgeResult(
            checks=[Check("key_point", True, detail="rent is 1200", reason="stated")],
            usage=None,
            error=None,
        )
    )

    case = _case(expect=Expect(key_points=("rent is 1200",)))

    result = await run.run_case(case, USER, MODEL, judge)

    assert result["answer"] == "Your rent is $1,200."
    [(_, answer, *_rest)] = judge.calls
    assert answer == "Your rent is $1,200."
