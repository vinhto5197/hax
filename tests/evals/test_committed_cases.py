"""The committed case set loads, names only corpus documents it ships, and
covers every kind of case the eval exists to measure."""

from pathlib import Path

from evals.cases import load_cases

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "cases.jsonl"
CORPUS = ROOT / "evals" / "corpus"
TAGS = {"retrieval", "honesty", "tools", "general", "note", "history", "table"}


def test_committed_cases_load():
    cases = load_cases(CASES)
    corpus = {p.name for p in CORPUS.iterdir()}

    assert cases
    for case in cases:
        assert set(case.documents) <= corpus, case.id
        passage = case.expect.passage
        if passage is not None:
            assert passage.document in case.documents, case.id
            text = (CORPUS / passage.document).read_text()
            assert passage.contains.lower() in text.lower(), case.id
    assert TAGS <= {tag for case in cases for tag in case.tags}


def test_every_retrieval_case_checks_that_it_searched():
    # Grounding counts the key points as support (evals/judge.py), so a
    # retrieval case without a tools check would pass an answer from memory.
    for case in load_cases(CASES):
        if "retrieval" in case.tags:
            assert case.expect.tools and "search_documents" in case.expect.tools, (
                case.id
            )


def test_every_committed_case_checks_something():
    # A case with nothing to check is an error at run time; the shipped file
    # never carries one.
    for case in load_cases(CASES):
        e = case.expect
        gradable = (
            e.tools is not None
            or e.exact_reply is not None
            or e.contains_any
            or e.contains_none
            or e.table
            or e.key_points
            or e.grounded
        )
        assert gradable, case.id
