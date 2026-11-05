"""The run report: a summary over case results, a comparison between two runs,
the baseline pointer, and the terminal and HTML renderings of one run."""

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

import pytest
from evals.report import compare, load_baseline, render_html, render_terminal, summarize

SUMMARY_KEYS = {"cases", "must", "probes", "by_check", "by_tag", "retrieval", "errors"}


def _check(
    name: str = "tools",
    passed: bool = True,
    detail: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {"check": name, "pass": passed, "detail": detail, "reason": reason}


def _case(
    id: str,
    outcome: str = "pass",
    tier: str = "must",
    tags: tuple[str, ...] = (),
    checks: list[dict[str, Any]] | None = None,
    hash: str = "h1",
    retrieval: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": id,
        "tier": tier,
        "tags": list(tags),
        "question": f"question for {id}",
        "context": {"documents": [], "note": None, "history": []},
        "answer": f"answer for {id}",
        "tools_fired": [],
        "checks": checks
        if checks is not None
        else [_check("tools", outcome == "pass")],
        "outcome": outcome,
        "error": "boom" if outcome == "error" else None,
        "case_hash": hash,
        "seen": {"passages": [], "tool_outputs": [], "note": None},
        "retrieval": retrieval,
        "tokens": {"in": 100, "out": 20},
        "seconds": 1.5,
    }
    case.update(overrides)
    return case


def _run(
    cases: list[dict[str, Any]],
    baseline: str | None = None,
    broke: list[str] | None = None,
    fixed: list[str] | None = None,
    model_usd: float = 0.0123,
    judge_usd: float = 0.4567,
) -> dict[str, Any]:
    summary = summarize(cases)
    summary["flips"] = {"broke": broke or [], "fixed": fixed or []}
    summary["cost"] = {
        "model": {"in": 1000, "out": 200, "usd_estimate": model_usd},
        "judge": {"in": 3000, "out": 400, "usd_estimate": judge_usd},
    }
    summary["seconds"] = 12.5
    return {
        "run": {
            "started": "2026-11-05T10:00:00Z",
            "commit": "37d25e8",
            "dirty": False,
            "model": "claude-haiku-4-5",
            "judge": "claude-sonnet-4-6",
            "settings": {"top_k": 5, "rag_max_distance": None},
            "baseline": baseline,
        },
        "summary": summary,
        "cases": cases,
    }


class _Sections(HTMLParser):
    """Collects each `section.case` as (id, outcome, text inside it)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict[str, Any]] = []
        self._depth = 0  # section nesting depth inside the current case section

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "section":
            return
        attr = dict(attrs)
        if self._depth == 0 and "case" in (attr.get("class") or "").split():
            self.sections.append(
                {"id": attr.get("id"), "outcome": attr.get("data-outcome"), "text": []}
            )
            self._depth = 1
        elif self._depth:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._depth:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._depth:
            self.sections[-1]["text"].append(data)


def _sections(html: str) -> list[dict[str, Any]]:
    parser = _Sections()
    parser.feed(html)
    for section in parser.sections:
        section["text"] = "".join(section["text"])
    return parser.sections


# --- summarize -------------------------------------------------------------


def test_summary_counts_must_and_probes_apart():
    cases = [
        _case("m1", "pass", "must"),
        _case("m2", "fail", "must"),
        _case("p1", "pass", "probe"),
        _case("p2", "pass", "probe"),
        _case("p3", "fail", "probe"),
    ]

    summary = summarize(cases)

    assert set(summary) == SUMMARY_KEYS
    assert summary["cases"] == 5
    assert summary["must"] == "1/2"
    assert summary["probes"] == "2/3"
    assert summary["errors"] == []

    empty = summarize([])
    assert set(empty) == SUMMARY_KEYS
    assert empty["cases"] == 0
    assert empty["must"] == "0/0"
    assert empty["probes"] == "0/0"
    assert empty["by_check"] == {}
    assert empty["by_tag"] == {}
    assert empty["retrieval"] == {"recall_at_k": "0/0"}
    assert empty["errors"] == []


def test_summary_errors_count_in_total_not_passed():
    cases = [
        _case("zeta", "error", "must"),
        _case("beta", "pass", "must"),
        _case("alpha", "error", "probe"),
    ]

    summary = summarize(cases)

    assert summary["cases"] == 3
    assert summary["must"] == "1/2"
    assert summary["probes"] == "0/1"
    assert summary["errors"] == ["zeta", "alpha"]


def test_summary_by_check_and_tag():
    cases = [
        _case(
            "a",
            "pass",
            tags=("retrieval", "memory"),
            checks=[
                _check("tools", True),
                _check("key_point", True, detail="point one"),
                _check("key_point", True, detail="point two"),
            ],
        ),
        _case(
            "b",
            "fail",
            tags=("retrieval",),
            checks=[
                _check("tools", True),
                _check("key_point", False, detail="point three", reason="missing"),
                _check("grounded", False, reason="invented a date"),
            ],
        ),
        _case(
            "c",
            "error",
            tags=("retrieval",),
            checks=[_check("tools", False), _check("table", False)],
        ),
    ]

    summary = summarize(cases)

    assert summary["by_check"] == {
        "tools": "2/2",
        "key_point": "2/3",
        "grounded": "0/1",
    }
    assert summary["by_tag"] == {"retrieval": "1/3", "memory": "1/1"}


def test_recall_at_k_counts_only_cases_with_a_passage():
    cases = [
        _case("no-search", retrieval=None),
        _case("search-only", retrieval={"distance": 0.3, "nearest_distance": 0.2}),
        _case(
            "hit-1",
            retrieval={
                "expected_passage_rank": 1,
                "distance": 0.2,
                "nearest_distance": 0.2,
            },
        ),
        _case(
            "miss",
            "fail",
            retrieval={
                "expected_passage_rank": None,
                "distance": None,
                "nearest_distance": 0.4,
            },
        ),
        _case(
            "hit-3",
            retrieval={
                "expected_passage_rank": 3,
                "distance": 0.35,
                "nearest_distance": 0.1,
            },
        ),
    ]

    assert summarize(cases)["retrieval"] == {"recall_at_k": "2/3"}


# --- compare ---------------------------------------------------------------


def _ids(result: dict[str, Any]) -> dict[str, list[str]]:
    return {k: result[k] for k in ("broke", "fixed", "changed", "added", "removed")}


def test_compare_broke_and_fixed():
    a = _run(
        [
            _case("m", "pass"),
            _case("b", "pass"),
            _case("y", "fail"),
            _case("same-pass", "pass"),
            _case("same-fail", "fail"),
        ]
    )
    b = _run(
        [
            _case("m", "fail"),
            _case("b", "fail"),
            _case("y", "pass"),
            _case("same-pass", "pass"),
            _case("same-fail", "fail"),
        ]
    )

    assert _ids(compare(a, b)) == {
        "broke": ["b", "m"],
        "fixed": ["y"],
        "changed": [],
        "added": [],
        "removed": [],
    }


def test_compare_changed_hash_is_not_a_flip():
    a = _run(
        [_case("edited", "pass", hash="h1"), _case("edited-too", "fail", hash="h1")]
        + [_case("reworded", "pass", hash="h1")]
    )
    b = _run(
        [_case("edited", "fail", hash="h2"), _case("edited-too", "pass", hash="h2")]
        + [_case("reworded", "pass", hash="h9")]
    )

    result = compare(a, b)

    assert result["broke"] == []
    assert result["fixed"] == []
    assert result["changed"] == ["edited", "edited-too", "reworded"]


def test_compare_added_and_removed():
    a = _run([_case("kept"), _case("old-z"), _case("old-a")])
    b = _run([_case("kept"), _case("new-z"), _case("new-a")])

    result = compare(a, b)

    assert result["added"] == ["new-a", "new-z"]
    assert result["removed"] == ["old-a", "old-z"]
    assert result["broke"] == []
    assert result["fixed"] == []
    assert result["changed"] == []


def test_compare_error_is_never_a_flip():
    a = _run(
        [_case("e-then-pass", "error"), _case("pass-then-e", "pass")]
        + [_case("fail-then-e", "fail"), _case("e-then-fail", "error")]
    )
    b = _run(
        [_case("e-then-pass", "pass"), _case("pass-then-e", "error")]
        + [_case("fail-then-e", "error"), _case("e-then-fail", "fail")]
    )

    assert _ids(compare(a, b)) == {
        "broke": [],
        "fixed": [],
        "changed": [],
        "added": [],
        "removed": [],
    }


def test_compare_by_check_delta():
    a = _run(
        [
            _case(
                "c1", "pass", checks=[_check("tools", True), _check("key_point", True)]
            ),
            _case(
                "c2", "fail", checks=[_check("tools", False), _check("key_point", True)]
            ),
            _case("c3", "pass", checks=[_check("table", True)]),
        ]
    )
    b = _run(
        [
            _case(
                "c1", "pass", checks=[_check("tools", True), _check("key_point", True)]
            ),
            _case(
                "c2", "pass", checks=[_check("tools", True), _check("key_point", True)]
            ),
            _case("c4", "pass", checks=[_check("grounded", True)]),
        ]
    )
    assert a["summary"]["by_check"] == {
        "tools": "1/2",
        "key_point": "2/2",
        "table": "1/1",
    }

    assert compare(a, b)["by_check_delta"] == {
        "tools": "1/2→2/2",
        "key_point": "2/2→2/2",
        "table": "1/1→—",
        "grounded": "—→1/1",
    }


# --- load_baseline -----------------------------------------------------------


def _no_pointer(tmp: Path) -> None:
    (tmp / "runs").mkdir()


def _pointer_not_json(tmp: Path) -> None:
    (tmp / "baseline.json").write_text("{not json")


def _pointer_without_run(tmp: Path) -> None:
    (tmp / "baseline.json").write_text(json.dumps({"file": "r1.json"}))


def _target_missing(tmp: Path) -> None:
    (tmp / "runs").mkdir()
    (tmp / "baseline.json").write_text(json.dumps({"run": "gone.json"}))


def _target_not_json(tmp: Path) -> None:
    (tmp / "runs").mkdir()
    (tmp / "runs" / "r1.json").write_text("{truncated")
    (tmp / "baseline.json").write_text(json.dumps({"run": "r1.json"}))


@pytest.mark.parametrize(
    "setup",
    [
        _no_pointer,
        _pointer_not_json,
        _pointer_without_run,
        _target_missing,
        _target_not_json,
    ],
    ids=[
        "no-pointer",
        "pointer-not-json",
        "pointer-without-run",
        "target-missing",
        "target-not-json",
    ],
)
def test_missing_baseline_reports_none(tmp_path: Path, setup: Callable[[Path], None]):
    setup(tmp_path)

    assert load_baseline(tmp_path / "baseline.json") is None


def test_baseline_loads_the_pointed_run(tmp_path: Path):
    run = _run([_case("a"), _case("b", "fail")])
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "2026-11-05-a.json").write_text(json.dumps(run))
    (tmp_path / "runs" / "2026-11-04-b.json").write_text(
        json.dumps(_run([_case("other")]))
    )
    pointer = tmp_path / "baseline.json"
    pointer.write_text(json.dumps({"run": "2026-11-05-a.json"}))

    assert load_baseline(pointer) == run


# --- render_html -------------------------------------------------------------


def test_html_lists_failures_first():
    cases = [
        _case("p1", "pass"),
        _case("f1", "fail"),
        _case("e1", "error"),
        _case("p2", "pass"),
        _case("f2", "fail"),
        _case("e2", "error"),
    ]

    sections = _sections(render_html(_run(cases)))

    assert [(s["id"], s["outcome"]) for s in sections] == [
        ("case-f1", "fail"),
        ("case-f2", "fail"),
        ("case-e1", "error"),
        ("case-e2", "error"),
        ("case-p1", "pass"),
        ("case-p2", "pass"),
    ]


def test_html_escapes_answers():
    cases = [_case("xss", "fail", answer="<script>alert(1)</script>")]

    html = render_html(_run(cases))

    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_html_has_every_case():
    rich = _case(
        "rich",
        "fail",
        tags=("retrieval",),
        question="Which case marks the direct object?",
        context={
            "documents": ["nevron_grammar.md"],
            "note": "I study Nevron on weekends",
            "history": [
                ["user", "earlier user turn"],
                ["assistant", "earlier assistant turn"],
            ],
        },
        answer="The accusative, marked by -en.",
        seen={
            "passages": ["Nevron marks the direct object with the suffix -en."],
            "tool_outputs": [],
            "note": "I study Nevron on weekends",
        },
        checks=[
            _check("tools", True),
            _check(
                "key_point", False, detail="names the accusative", reason="said dative"
            ),
            _check("grounded", False, reason="claimed a source it never saw"),
        ],
        retrieval={
            "expected_passage_rank": 7,
            "distance": 0.25,
            "nearest_distance": 0.125,
        },
    )
    cases = [
        rich,
        _case("plain-a"),
        _case("plain-b", "error"),
        _case("plain-c", "fail"),
    ]

    sections = _sections(render_html(_run(cases)))

    ids = [s["id"] for s in sections]
    assert sorted(ids) == sorted(f"case-{c['id']}" for c in cases)
    assert len(ids) == len(set(ids))

    text = next(s["text"] for s in sections if s["id"] == "case-rich")
    for expected in (
        "Which case marks the direct object?",
        "I study Nevron on weekends",
        "earlier user turn",
        "earlier assistant turn",
        "Nevron marks the direct object with the suffix -en.",
        "The accusative, marked by -en.",
        "tools",
        "key_point",
        "names the accusative",
        "said dative",
        "grounded",
        "claimed a source it never saw",
        "7",
        "0.25",
        "0.125",
    ):
        assert expected in text, expected


def test_html_is_self_contained():
    html = render_html(_run([_case("a"), _case("b", "fail")]))

    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "<style" in html.lower()
    assert "prefers-color-scheme" in html
    assert not re.search(r"<script[^>]*\bsrc\s*=", html, re.IGNORECASE)
    assert not re.search(r"<link[^>]*stylesheet", html, re.IGNORECASE)
    assert not re.search(
        r"<link[^>]*href\s*=\s*[\"']?(https?:)?//", html, re.IGNORECASE
    )


# --- render_terminal ---------------------------------------------------------


def test_terminal_shows_flips_and_both_costs():
    cases = [
        _case(
            "bk-case",
            "fail",
            checks=[_check("tools", False), _check("key_point", True)],
        ),
        _case("fx-case", "pass", tier="probe", checks=[_check("tools", True)]),
        _case("err-case", "error"),
        _case(
            "hit",
            retrieval={
                "expected_passage_rank": 1,
                "distance": 0.2,
                "nearest_distance": 0.2,
            },
        ),
    ]
    run = _run(
        cases,
        baseline="2026-11-04-base.json",
        broke=["bk-case"],
        fixed=["fx-case"],
        model_usd=0.0123,
        judge_usd=0.4567,
    )
    summary = run["summary"]

    text = render_terminal(run)

    assert "claude-haiku-4-5" in text
    assert summary["must"] in text
    assert summary["probes"] in text
    for name, value in summary["by_check"].items():
        assert name in text and value in text
    assert summary["retrieval"]["recall_at_k"] in text
    assert "err-case" in text
    assert "$0.0123" in text
    assert "$0.4567" in text
    assert "model" in text
    assert "judge" in text
    assert "bk-case" in text
    assert "fx-case" in text


def test_terminal_says_no_baseline():
    run = _run([_case("a"), _case("b", "fail")], baseline=None)

    assert "no baseline" in render_terminal(run)


@pytest.mark.parametrize("kind", ["parent", "absolute", "not-a-string"])
def test_baseline_pointer_names_a_file_in_runs_only(tmp_path: Path, kind: str):
    outside = tmp_path / "eval" / "outside.json"
    (tmp_path / "eval" / "runs").mkdir(parents=True)
    outside.write_text(json.dumps(_run([_case("a")])))
    name = {"parent": "../outside.json", "absolute": str(outside), "not-a-string": 5}
    pointer = tmp_path / "eval" / "baseline.json"
    pointer.write_text(json.dumps({"run": name[kind]}))

    assert load_baseline(pointer) is None


def test_baseline_that_is_not_a_run_reports_none(tmp_path: Path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "r.json").write_text("[]")
    pointer = tmp_path / "baseline.json"
    pointer.write_text(json.dumps({"run": "r.json"}))

    assert load_baseline(pointer) is None


def test_html_escapes_ids_in_attributes():
    out = render_html(_run([_case('a" onmouseover="x', tags=("<b>",))]))

    assert 'onmouseover="x"' not in out
    assert "<b>" not in out


def test_terminal_survives_a_partial_run_file():
    run = _run([_case("a")], baseline="old.json")
    del run["summary"]["flips"], run["summary"]["cost"], run["summary"]["seconds"]

    out = render_terminal(run)

    assert "broke none" in out
    assert "old.json" in out
