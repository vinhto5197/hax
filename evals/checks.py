"""The checks code can settle without a model: which tools fired, and what the
answer's text contains. The judge (evals/judge.py) adds key points and
grounding as Checks of the same shape.
"""

import re
from dataclasses import dataclass

from evals.cases import Expect

# A header row holding a pipe, then a GFM separator row: dashes with optional
# alignment colons, outer pipes optional, so a separator with no leading pipe
# needs two cells (a bare "---" under a line is a rule, not a table).
_CELL = r"[ \t]*:?-+:?[ \t]*"
_TABLE = re.compile(
    rf"^[^\n]*\|[^\n]*\n(?:[ \t]*(?:\|{_CELL})+\|?|{_CELL}(?:\|{_CELL})+\|?)[ \t]*$",
    re.MULTILINE,
)


@dataclass
class Check:
    check: str
    passed: bool
    detail: str | None = None
    reason: str | None = None


# Typographic forms a model writes for the same text: curly quotes and
# apostrophes, and every dash, so "Don’t" and "–en" match "Don't" and "-en".
_FOLD = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)


def normalize(text: str) -> str:
    return " ".join(text.lower().translate(_FOLD).replace(",", "").split())


def code_checks(expect: Expect, answer: str, tools_fired: list[str]) -> list[Check]:
    checks: list[Check] = []
    said = normalize(answer)
    if expect.tools is not None:
        fired = set(tools_fired)
        ok = fired == expect.tools
        checks.append(
            Check("tools", ok, None if ok else f"fired {sorted(fired) or 'none'}")
        )
    if expect.exact_reply is not None:
        ok = said == normalize(expect.exact_reply)
        checks.append(Check("exact_reply", ok, None if ok else f"replied {said!r}"))
    if expect.contains_any:
        ok = any(normalize(n) in said for n in expect.contains_any)
        checks.append(Check("contains_any", ok, None if ok else "none of them found"))
    if expect.contains_none:
        found = [n for n in expect.contains_none if normalize(n) in said]
        checks.append(
            Check("contains_none", not found, f"found {found}" if found else None)
        )
    if expect.table:
        ok = bool(_TABLE.search(answer.replace("\r\n", "\n")))
        checks.append(Check("table", ok, None if ok else "no Markdown table"))
    return checks
