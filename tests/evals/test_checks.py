"""Code checks over one answer: one Check per expectation the case names, in
a fixed order; text compared after normalization (case, commas, spacing)."""

from typing import Any

from evals.cases import Expect, Passage
from evals.checks import Check, code_checks


def _expect(**overrides: Any) -> Expect:
    return Expect(**overrides)


def _only(checks: list[Check], name: str) -> Check:
    matching = [c for c in checks if c.check == name]
    assert len(matching) == 1, checks
    return matching[0]


def _passes(expect: Expect, answer: str, tools_fired: list[str] | None = None) -> bool:
    checks = code_checks(expect, answer, tools_fired or [])
    assert len(checks) == 1, checks
    check = checks[0]
    if not check.passed:
        assert isinstance(check.detail, str) and check.detail
    return check.passed


def test_tools_exact_set():
    expect = _expect(tools=frozenset({"search_documents"}))

    assert _passes(expect, "a", ["search_documents"])
    assert not _passes(expect, "a", ["search_documents", "calculator"])
    assert not _passes(expect, "a", [])
    assert _passes(expect, "a", ["search_documents", "search_documents"])

    two = _expect(tools=frozenset({"search_documents", "calculator"}))
    assert not _passes(two, "a", ["calculator"])
    assert _passes(two, "a", ["calculator", "search_documents"])


def test_empty_tool_set_means_none_fired():
    expect = _expect(tools=frozenset())

    assert _passes(expect, "a", [])
    assert not _passes(expect, "a", ["get_current_datetime"])


def test_exact_reply_ignores_case_and_spacing():
    expect = _expect(exact_reply="Don't bro. You don't want chicken legs bro.")

    assert _passes(expect, "  don't BRO.\nyou don't want chicken legs bro. ")
    assert not _passes(expect, "Do it bro. You want chicken legs bro.")


def test_contains_any_and_none():
    any_ = _expect(contains_any=("-en", "accusative"))
    assert _passes(any_, "The ACCUSATIVE is marked so.")
    assert _passes(any_, "It ends in -EN.")
    assert not _passes(any_, "The dative is marked by -um.")

    none = _expect(contains_none=("I don't know", "no documents"))
    assert _passes(none, "The suffix is -en.")
    assert not _passes(none, "Sorry, i   DON'T know.")


def test_commas_are_ignored():
    assert _passes(_expect(contains_any=("1000",)), "The total is 1,000 dollars.")
    assert _passes(_expect(contains_any=("1,000",)), "The total is 1000 dollars.")
    assert not _passes(_expect(contains_none=("1000",)), "It cost 1,000.")
    assert _passes(_expect(exact_reply="1,000"), "1000")


def test_table_detects_header_and_separator():
    expect = _expect(table=True)

    plain = "Here:\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    aligned = "| name | total |\n| :--- | ---: |\n| x | 3 |"
    centred = "|a|b|c|\n|:-:|---|:--|\n|1|2|3|"
    assert _passes(expect, plain)
    assert _passes(expect, aligned)
    assert _passes(expect, centred)

    prose = "Use a | b or c | d when piping commands."
    no_header = "Results:\n|---|---|\n| 1 | 2 |"
    lone = "|---|"
    gap = "| a | b |\n\n|---|---|\n| 1 | 2 |"
    assert not _passes(expect, prose)
    assert not _passes(expect, no_header)
    assert not _passes(expect, lone)
    assert not _passes(expect, gap)


def test_empty_answer_fails_text_checks():
    expect = _expect(
        exact_reply="hello",
        contains_any=("hello",),
        contains_none=("goodbye",),
        table=True,
    )

    checks = code_checks(expect, "", [])

    for name in ("exact_reply", "contains_any", "table"):
        check = _only(checks, name)
        assert check.passed is False
        assert isinstance(check.detail, str) and check.detail
    assert _only(checks, "contains_none").passed is True


def test_unnamed_expectations_produce_no_checks():
    assert code_checks(_expect(), "anything", ["search_documents"]) == []

    judge_only = _expect(
        key_points=("the suffix is -en",),
        grounded=True,
        passage=Passage(document="nevron_grammar.md", contains="accusative"),
    )
    assert code_checks(judge_only, "anything", ["search_documents"]) == []


def test_checks_come_in_a_fixed_order():
    expect = _expect(
        tools=frozenset({"search_documents"}),
        exact_reply="x",
        contains_any=("x",),
        contains_none=("y",),
        table=True,
    )

    checks = code_checks(expect, "x", ["search_documents"])

    assert [c.check for c in checks] == [
        "tools",
        "exact_reply",
        "contains_any",
        "contains_none",
        "table",
    ]

    partial = _expect(table=True, tools=frozenset(), contains_none=("y",))
    assert [c.check for c in code_checks(partial, "x", [])] == [
        "tools",
        "contains_none",
        "table",
    ]


def test_table_forms_models_produce():
    expect = _expect(table=True)
    assert _passes(expect, "a | b\n--|--\n1 | 2")  # no outer pipes
    assert _passes(expect, "| a | b\n|---|---\n| 1 | 2")  # leading pipe only
    assert _passes(expect, "| a | b |\r\n|---|---|\r\n| 1 | 2 |")  # CRLF
    assert _passes(expect, "Here:\n\n| a |\n|---|")  # one column, at the end
    assert not _passes(expect, "a | b\n---")  # a rule under prose
