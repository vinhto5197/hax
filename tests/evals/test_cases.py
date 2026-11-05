"""The eval case file: JSON lines, one case per line, loaded into frozen
dataclasses with defaults; every rejection names the file and the 1-based
physical line."""

import json
import re
from pathlib import Path

import pytest
from evals.cases import Case, CaseFileError, Expect, Passage, load_cases

FULL = {
    "id": "grammar-fact",
    "tier": "must",
    "tags": ["retrieval"],
    "question": (
        "According to my documents, which suffix marks the accusative in Nevron?"
    ),
    "context": {
        "documents": ["nevron_grammar.md"],
        "note": None,
        "history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    },
    "expect": {
        "tools": ["search_documents"],
        "key_points": ["the accusative suffix is -en"],
        "grounded": True,
        "contains_any": ["-en"],
        "contains_none": ["I don't know"],
        "exact_reply": None,
        "table": False,
        "passage": {"document": "nevron_grammar.md", "contains": "accusative"},
    },
}


def _write(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _line(obj: dict) -> str:
    return json.dumps(obj)


def _assert_error_at(path: Path, lineno: int) -> None:
    with pytest.raises(CaseFileError) as exc:
        load_cases(path)
    assert str(exc.value).startswith(f"{path}:{lineno}: ")


def test_loads_a_full_case(tmp_path):
    path = _write(tmp_path, _line(FULL))

    cases = load_cases(path)

    assert len(cases) == 1
    case = cases[0]
    assert isinstance(case, Case)
    assert case.id == "grammar-fact"
    assert case.tier == "must"
    assert case.tags == ("retrieval",)
    assert case.question == FULL["question"]
    assert case.documents == ("nevron_grammar.md",)
    assert case.note is None
    assert case.history == (("user", "hi"), ("assistant", "hello"))
    assert isinstance(case.expect, Expect)
    assert case.expect.tools == frozenset({"search_documents"})
    assert isinstance(case.expect.tools, frozenset)
    assert case.expect.key_points == ("the accusative suffix is -en",)
    assert case.expect.grounded is True
    assert case.expect.contains_any == ("-en",)
    assert case.expect.contains_none == ("I don't know",)
    assert case.expect.exact_reply is None
    assert case.expect.table is False
    assert case.expect.passage == Passage(
        document="nevron_grammar.md", contains="accusative"
    )
    assert re.fullmatch(r"[0-9a-f]{12}", case.line_hash)


def test_loads_a_note_and_probe_tier(tmp_path):
    obj = {
        "id": "n",
        "tier": "probe",
        "question": "q",
        "context": {"note": "I live in Lisbon"},
    }
    case = load_cases(_write(tmp_path, _line(obj)))[0]

    assert case.tier == "probe"
    assert case.note == "I live in Lisbon"


def test_optional_fields_default(tmp_path):
    case = load_cases(_write(tmp_path, '{"id": "x", "question": "q"}'))[0]

    assert case.id == "x"
    assert case.question == "q"
    assert case.tier == "must"
    assert case.tags == ()
    assert case.documents == ()
    assert case.note is None
    assert case.history == ()
    e = case.expect
    assert e.tools is None
    assert e.key_points == ()
    assert e.grounded is False
    assert e.exact_reply is None
    assert e.contains_any == ()
    assert e.contains_none == ()
    assert e.table is False
    assert e.passage is None


def test_partial_expect_defaults_the_rest(tmp_path):
    obj = {"id": "x", "question": "q", "expect": {"tools": []}}
    e = load_cases(_write(tmp_path, _line(obj)))[0].expect

    assert e.tools == frozenset()
    assert e.key_points == ()
    assert e.grounded is False
    assert e.exact_reply is None
    assert e.contains_any == ()
    assert e.contains_none == ()
    assert e.table is False
    assert e.passage is None


def test_blank_lines_skipped_but_counted(tmp_path):
    path = _write(
        tmp_path,
        '{"id": "a", "question": "q"}',
        "   ",
        '{"id": "b", "question": "q"}',
    )
    assert [c.id for c in load_cases(path)] == ["a", "b"]

    bad = _write(tmp_path, '{"id": "a", "question": "q"}', "", "{not json")
    _assert_error_at(bad, 3)


def test_bad_json_rejected_with_line(tmp_path):
    path = _write(tmp_path, '{"id": "a", "question": "q"}', '{"id": "b", ')
    _assert_error_at(path, 2)


@pytest.mark.parametrize(
    "obj",
    [
        {"id": "x", "question": "q", "bogus": 1},
        {"id": "x", "question": "q", "context": {"bogus": 1}},
        {"id": "x", "question": "q", "expect": {"bogus": 1}},
    ],
    ids=["top-level", "context", "expect"],
)
def test_unknown_key_rejected_with_line(tmp_path, obj):
    path = _write(tmp_path, '{"id": "a", "question": "q"}', _line(obj))
    _assert_error_at(path, 2)


@pytest.mark.parametrize(
    "obj",
    [{"question": "q"}, {"id": "x"}],
    ids=["missing-id", "missing-question"],
)
def test_missing_id_or_question_rejected_with_line(tmp_path, obj):
    path = _write(tmp_path, '{"id": "a", "question": "q"}', _line(obj))
    _assert_error_at(path, 2)


def test_duplicate_id_rejected_with_line(tmp_path):
    path = _write(
        tmp_path,
        '{"id": "a", "question": "q"}',
        '{"id": "b", "question": "q"}',
        '{"id": "a", "question": "other"}',
    )
    _assert_error_at(path, 3)


@pytest.mark.parametrize("tier", ["should", "MUST", ""])
def test_bad_tier_rejected_with_line(tmp_path, tier):
    obj = {"id": "x", "question": "q", "tier": tier}
    path = _write(tmp_path, _line(obj))
    _assert_error_at(path, 1)


def test_line_hash_changes_when_the_line_changes(tmp_path):
    first = load_cases(_write(tmp_path, '{"id": "x", "question": "q1"}'))[0]
    changed = load_cases(_write(tmp_path, '{"id": "x", "question": "q2"}'))[0]
    same = load_cases(_write(tmp_path, '{"id": "x", "question": "q1"}'))[0]

    assert first.line_hash != changed.line_hash
    assert first.line_hash == same.line_hash


@pytest.mark.parametrize(
    "field",
    [
        {"grounded": "no"},
        {"table": "false"},
        {"exact_reply": 5},
        {"exact_reply": "  "},
        {"contains_any": [""]},
        {"contains_none": ["  "]},
        {"key_points": [""]},
    ],
)
def test_wrongly_typed_or_empty_expectation_rejected_with_line(tmp_path, field):
    path = _write(tmp_path, _line({"id": "x", "question": "q", "expect": field}))
    _assert_error_at(path, 1)


@pytest.mark.parametrize("bad_id", ["", "   "])
def test_blank_id_rejected_with_line(tmp_path, bad_id):
    path = _write(tmp_path, _line({"id": bad_id, "question": "q"}))
    _assert_error_at(path, 1)


def test_non_utf8_file_rejected_as_case_file_error(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_bytes(b'{"id": "x", "question": "caf\xe9"}\n')
    with pytest.raises(CaseFileError, match=re.escape(str(path))):
        load_cases(path)


def test_line_separator_inside_a_string_stays_one_case(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        # The escape keeps the source free of a raw U+2028; the file written
        # holds the raw character, as ensure_ascii=False writes it.
        json.dumps({"id": "x", "question": "a\u2028b"}, ensure_ascii=False)
        + "\n"
        + _line({"id": "y", "question": "q", "tier": "bad"})
        + "\n",
        encoding="utf-8",
    )
    _assert_error_at(path, 2)


def test_line_hash_ignores_line_endings(tmp_path):
    line = _line({"id": "x", "question": "q"})
    lf = tmp_path / "lf.jsonl"
    crlf = tmp_path / "crlf.jsonl"
    lf.write_bytes((line + "\n").encode())
    crlf.write_bytes((line + "\r\n").encode())
    assert load_cases(lf)[0].line_hash == load_cases(crlf)[0].line_hash
