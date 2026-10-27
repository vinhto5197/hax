"""Print one ISO week of this project's Claude Code transcripts, reduced to what
a retro needs: the maintainer's typed messages and every tool call that was
refused or failed, oldest first.

The transcripts under ~/.claude/projects/ are append-only and never compacted,
so they hold what the session's context lost; the Friday retro (skill
morning-digest) reads this output instead of the controller's recollection.
Read-only; prints to stdout.

    .venv/bin/python scripts/week_transcript.py            # this week
    .venv/bin/python scripts/week_transcript.py 2026-W44
"""

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Claude Code names a project's transcript folder after its path, "/" -> "-";
# worktree sessions get sibling folders with the same prefix.
PROJECTS = Path.home() / ".claude" / "projects"
PREFIX = str(ROOT).replace("/", "-")

# Harness wrappers around a typed message (IDE context, reminders, commands).
_WRAPPER = re.compile(r"<([a-z][a-z0-9_-]*)\b[^>]*>.*?</\1>", re.S)
_DENIED = "Permission for this action was denied"


def week_bounds(week: str) -> tuple[dt.datetime, dt.datetime]:
    year, num = week.split("-W")
    start = dt.datetime.fromisocalendar(int(year), int(num), 1).replace(tzinfo=dt.UTC)
    return start, start + dt.timedelta(days=7)


def typed_text(content) -> str:
    parts = (
        [content]
        if isinstance(content, str)
        else [c.get("text", "") for c in content if c.get("type") == "text"]
    )
    return " ".join(_WRAPPER.sub("", p).strip() for p in parts).strip()


def tool_failures(content) -> list[str]:
    out = []
    for c in content if isinstance(content, list) else []:
        if c.get("type") != "tool_result":
            continue
        body = c.get("content")
        text = (
            body
            if isinstance(body, str)
            else " ".join(b.get("text", "") for b in body or [] if isinstance(b, dict))
        )
        if _DENIED in text:
            out.append("DENIED " + text[:240])
        elif c.get("is_error"):
            out.append("ERROR  " + text[:240])
    return out


def events(path: Path, start: dt.datetime, end: dt.datetime):
    with path.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "user" or d.get("isMeta") or d.get("isCompactSummary"):
                continue
            ts = d.get("timestamp")
            if not ts:
                continue
            when = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if not start <= when < end:
                continue
            content = d.get("message", {}).get("content")
            if (d.get("origin") or {}).get("kind") == "human":
                text = typed_text(content)
                if text:
                    yield when, "YOU    " + text[:600]
            for failure in tool_failures(content):
                yield when, failure


def main() -> None:
    today = dt.date.today().isocalendar()
    week = sys.argv[1] if len(sys.argv) > 1 else f"{today[0]}-W{today[1]:02d}"
    start, end = week_bounds(week)
    rows = []
    for path in sorted(PROJECTS.glob(f"{PREFIX}*/*.jsonl")):
        rows.extend(events(path, start, end))
    for when, text in sorted(rows):
        print(when.strftime("%a %m-%d %H:%M"), " ".join(text.split()))


if __name__ == "__main__":
    main()
