"""The eval's case file: `evals/cases.jsonl`, one JSON object per line.

A case names the question, its frozen context (the documents its answer should
come from, an optional About-you note, prior turns) and what a good answer must
show. Every `expect` field is optional and a case runs only the checks it
names. The whole file is validated before any API call, so a typo costs nothing:
an error names the file and the physical line.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

TOP_KEYS = {"id", "tier", "tags", "question", "context", "expect"}
CONTEXT_KEYS = {"documents", "note", "history"}
EXPECT_KEYS = {
    "tools",
    "key_points",
    "grounded",
    "exact_reply",
    "contains_any",
    "contains_none",
    "table",
    "passage",
}


class CaseFileError(Exception):
    pass


@dataclass(frozen=True)
class Passage:
    document: str
    contains: str


@dataclass(frozen=True)
class Expect:
    # None: the tools are not checked. frozenset(): no tool may fire.
    tools: frozenset[str] | None = None
    key_points: tuple[str, ...] = ()
    grounded: bool = False
    exact_reply: str | None = None
    contains_any: tuple[str, ...] = ()
    contains_none: tuple[str, ...] = ()
    table: bool = False
    passage: Passage | None = None


@dataclass(frozen=True)
class Case:
    id: str
    tier: Literal["must", "probe"]
    tags: tuple[str, ...]
    question: str
    documents: tuple[str, ...]
    note: str | None
    history: tuple[tuple[Literal["user", "assistant"], str], ...]
    expect: Expect
    # Two runs compare a case by id only while this matches: an edited case is
    # reported as changed, never as a flip.
    line_hash: str


def _unknown(obj: dict, allowed: set[str], where: str) -> None:
    extra = sorted(set(obj) - allowed)
    if extra:
        raise ValueError(f"unknown {where} key(s): {', '.join(extra)}")


def _obj(value: Any, where: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    return value


def _strs(value: Any, where: str) -> tuple[str, ...]:
    # An empty needle would make contains_any always pass and contains_none
    # always fail.
    if not isinstance(value, list) or not all(
        isinstance(v, str) and v.strip() for v in value
    ):
        raise ValueError(f"{where} must be a list of non-empty strings")
    return tuple(value)


def _flag(raw: dict, key: str) -> bool:
    value = raw.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"expect.{key} must be true or false")
    return value


def _expect(raw: dict) -> Expect:
    _unknown(raw, EXPECT_KEYS, "expect")
    passage = None
    if raw.get("passage") is not None:
        p = _obj(raw["passage"], "expect.passage")
        _unknown(p, {"document", "contains"}, "expect.passage")
        if not isinstance(p.get("document"), str) or not isinstance(
            p.get("contains"), str
        ):
            raise ValueError("expect.passage needs document and contains strings")
        passage = Passage(document=p["document"], contains=p["contains"])
    tools = raw.get("tools")
    exact = raw.get("exact_reply")
    # An empty exact_reply would pass on an empty answer, hiding a turn that
    # produced no text.
    if exact is not None and not (isinstance(exact, str) and exact.strip()):
        raise ValueError("expect.exact_reply must be a non-empty string or null")
    return Expect(
        tools=None if tools is None else frozenset(_strs(tools, "expect.tools")),
        key_points=_strs(raw.get("key_points", []), "expect.key_points"),
        grounded=_flag(raw, "grounded"),
        exact_reply=exact,
        contains_any=_strs(raw.get("contains_any", []), "expect.contains_any"),
        contains_none=_strs(raw.get("contains_none", []), "expect.contains_none"),
        table=_flag(raw, "table"),
        passage=passage,
    )


def _history(raw: Any) -> tuple[tuple[Literal["user", "assistant"], str], ...]:
    if not isinstance(raw, list):
        raise ValueError("context.history must be a list")
    turns = []
    for turn in raw:
        t = _obj(turn, "a history turn")
        _unknown(t, {"role", "content"}, "history turn")
        if t.get("role") not in ("user", "assistant") or not isinstance(
            t.get("content"), str
        ):
            raise ValueError("a history turn needs role user|assistant and content")
        turns.append((cast(Literal["user", "assistant"], t["role"]), t["content"]))
    return tuple(turns)


def _case(line: str) -> Case:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON ({exc.msg})") from None
    raw = _obj(raw, "a case")
    _unknown(raw, TOP_KEYS, "top-level")
    for key in ("id", "question"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ValueError(f"missing {key}")
    tier = raw.get("tier", "must")
    if tier not in ("must", "probe"):
        raise ValueError(f"tier must be must or probe, not {tier!r}")
    context = _obj(raw.get("context", {}), "context")
    _unknown(context, CONTEXT_KEYS, "context")
    note = context.get("note")
    if note is not None and not isinstance(note, str):
        raise ValueError("context.note must be a string or null")
    return Case(
        id=raw["id"],
        tier=tier,
        tags=_strs(raw.get("tags", []), "tags"),
        question=raw["question"],
        documents=_strs(context.get("documents", []), "context.documents"),
        note=note,
        history=_history(context.get("history", [])),
        expect=_expect(_obj(raw.get("expect", {}), "expect")),
        line_hash=hashlib.sha256(line.encode()).hexdigest()[:12],
    )


def load_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    seen: dict[str, int] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CaseFileError(f"{path}: not UTF-8 ({exc.reason})") from None
    # split("\n"), not splitlines(): a JSON string may hold U+2028 and other
    # characters splitlines() breaks on. read_text has already turned CRLF
    # into LF, so line_hash does not depend on the line endings.
    for lineno, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            case = _case(line)
            if case.id in seen:
                raise ValueError(
                    f"duplicate id {case.id!r} (first on line {seen[case.id]})"
                )
        except ValueError as exc:
            raise CaseFileError(f"{path}:{lineno}: {exc}") from None
        seen[case.id] = lineno
        cases.append(case)
    return cases
