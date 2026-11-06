"""What a run is reduced to: the summary block, the comparison of two runs, and
the two renderings (terminal and a self-contained HTML page).

Everything here reads the results file's dicts only, so a saved run renders
and compares the same way years later. Comparison matches cases by id and
trusts a flip only when the case line is unchanged (`case_hash`); an `error`
on either side is never a flip, because an errored case says nothing about
the answer.
"""

import html
import json
from collections import defaultdict
from pathlib import Path


def _ratio(passed: int, total: int) -> str:
    return f"{passed}/{total}"


def summarize(cases: list[dict]) -> dict:
    # An error counts as not passed wherever cases are counted (tiers, tags),
    # and adds nothing where checks are counted: it produced no verdicts.
    def tier(name: str) -> str:
        group = [c for c in cases if c["tier"] == name]
        return _ratio(sum(c["outcome"] == "pass" for c in group), len(group))

    checks: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    tags: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    hits = expected = 0
    for case in cases:
        if case["outcome"] != "error":
            for check in case["checks"]:
                checks[check["check"]][0] += check["pass"]
                checks[check["check"]][1] += 1
        for tag in case["tags"]:
            tags[tag][0] += case["outcome"] == "pass"
            tags[tag][1] += 1
        retrieval = case.get("retrieval") or {}
        if "expected_passage_rank" in retrieval:
            expected += 1
            hits += retrieval["expected_passage_rank"] is not None
    return {
        "cases": len(cases),
        "must": tier("must"),
        "probes": tier("probe"),
        "by_check": {k: _ratio(*v) for k, v in checks.items()},
        "by_tag": {k: _ratio(*v) for k, v in tags.items()},
        "retrieval": {"recall_at_k": _ratio(hits, expected)},
        "errors": [c["id"] for c in cases if c["outcome"] == "error"],
    }


def compare(a: dict, b: dict) -> dict:
    old = {c["id"]: c for c in a["cases"]}
    new = {c["id"]: c for c in b["cases"]}
    broke, fixed, changed = [], [], []
    for cid in old.keys() & new.keys():
        was, now = old[cid], new[cid]
        if was["case_hash"] != now["case_hash"]:
            changed.append(cid)
        elif was["outcome"] == "pass" and now["outcome"] == "fail":
            broke.append(cid)
        elif was["outcome"] == "fail" and now["outcome"] == "pass":
            fixed.append(cid)
    a_checks = a["summary"]["by_check"]
    b_checks = b["summary"]["by_check"]
    return {
        "broke": sorted(broke),
        "fixed": sorted(fixed),
        "changed": sorted(changed),
        "added": sorted(new.keys() - old.keys()),
        "removed": sorted(old.keys() - new.keys()),
        "by_check_delta": {
            name: f"{a_checks.get(name, '—')}→{b_checks.get(name, '—')}"
            for name in sorted(a_checks.keys() | b_checks.keys())
        },
    }


def baseline_snapshot(run: dict, name: str) -> dict:
    """The committed baseline (evals/baseline.json): what compare() reads, each
    case's tier for a reader, and where it came from. No answers, questions or
    judge reasons: the repository is public, and outcomes alone are what a
    reviewer diffs."""
    meta = run["run"]
    return {
        "run": name,
        "commit": meta.get("commit"),
        "model": meta.get("model"),
        "judge": meta.get("judge"),
        "summary": {"by_check": run["summary"]["by_check"]},
        "cases": [
            {k: c[k] for k in ("id", "tier", "case_hash", "outcome")}
            for c in sorted(run["cases"], key=lambda c: c["id"])
        ],
    }


def load_baseline(path: Path) -> dict | None:
    # A missing or broken baseline means "no baseline", never a failed run.
    try:
        snapshot = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    # Hand edits and merge resolutions land here, and compare() runs after the
    # paid run: a shape it cannot read must be "no baseline", not a KeyError.
    try:
        if not isinstance(snapshot["summary"]["by_check"], dict):
            return None
        for case in snapshot["cases"]:
            if not {"id", "case_hash", "outcome"} <= case.keys():
                return None
    except (KeyError, TypeError, AttributeError):
        return None
    return snapshot


def _cost(label: str, cost: dict) -> str:
    return (
        f"{label}: ${cost['usd_estimate']:.4f} (estimate; "
        f"{cost['in']} in, {cost['out']} out)"
    )


def render_terminal(run: dict) -> str:
    meta, s = run["run"], run["summary"]
    lines = [
        f"model {meta['model']}, judge {meta['judge']}, commit {meta['commit']}"
        + (" (dirty)" if meta.get("dirty") else ""),
        f"must {s['must']}   probes {s['probes']}   cases {s['cases']}",
        "checks: " + ", ".join(f"{k} {v}" for k, v in sorted(s["by_check"].items())),
        f"retrieval recall@k {s['retrieval']['recall_at_k']}",
    ]
    if meta.get("baseline") is None:
        lines.append("flips: no baseline")
    else:
        flips = s.get("flips") or {"broke": [], "fixed": []}
        lines.append(
            f"flips against {meta['baseline']}: "
            f"broke {', '.join(flips['broke']) or 'none'}; "
            f"fixed {', '.join(flips['fixed']) or 'none'}"
        )
    if s["errors"]:
        lines.append(f"errors (run not trustworthy): {', '.join(s['errors'])}")
    for label in ("model", "judge"):
        if label in s.get("cost", {}):
            lines.append(_cost(label, s["cost"][label]))
    if "seconds" in s:
        lines.append(f"{s['seconds']:.0f}s")
    return "\n".join(lines)


_ORDER = {"fail": 0, "error": 1, "pass": 2}

_CSS = """
:root { color-scheme: light dark;
  --bg: #fff; --fg: #1d1d1f; --muted: #6e6e73; --line: #d2d2d7;
  --pass: #1a7f37; --fail: #c62828; --error: #a15c00; --card: #f6f6f8; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161618; --fg: #ececee; --muted: #9a9aa0; --line: #3a3a3e;
    --pass: #4ac26b; --fail: #ff6b6b; --error: #e0a33c; --card: #1f1f22; } }
body { background: var(--bg); color: var(--fg); margin: 0 auto; padding: 16px;
  max-width: 960px; font: 15px/1.5 system-ui, sans-serif; }
h1 { font-size: 20px; } h2 { font-size: 16px; margin: 0 0 8px; }
.meta, .label { color: var(--muted); }
.label { font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
  margin-top: 12px; }
.case { background: var(--card); border: 1px solid var(--line);
  border-left: 4px solid var(--line); border-radius: 8px; padding: 12px 16px;
  margin: 12px 0; overflow-wrap: anywhere; }
.case[data-outcome=pass] { border-left-color: var(--pass); }
.case[data-outcome=fail] { border-left-color: var(--fail); }
.case[data-outcome=error] { border-left-color: var(--error); }
.pass { color: var(--pass); } .fail { color: var(--fail); }
.error { color: var(--error); }
pre { white-space: pre-wrap; margin: 4px 0; font: 13px/1.45 ui-monospace,
  monospace; }
ul { margin: 4px 0; padding-left: 20px; }
summary { cursor: pointer; }
"""


def _e(value: object) -> str:
    return html.escape(str(value))


def _block(label: str, body: str) -> str:
    return f'<div class="label">{_e(label)}</div>{body}'


def _case_html(case: dict) -> str:
    outcome = case["outcome"]
    parts = [
        f'<h2><span class="{_e(outcome)}">{_e(outcome)}</span> '
        f'{_e(case["id"])} <span class="meta">{_e(case["tier"])}'
        f"{' · ' + _e(', '.join(case['tags'])) if case['tags'] else ''}</span></h2>",
        _block("question", f"<pre>{_e(case['question'])}</pre>"),
    ]
    context = case.get("context") or {}
    if context.get("note"):
        parts.append(_block("about you note", f"<pre>{_e(context['note'])}</pre>"))
    if context.get("history"):
        turns = "".join(
            f"<li><b>{_e(role)}</b>: {_e(text)}</li>"
            for role, text in context["history"]
        )
        parts.append(_block("earlier turns", f"<ul>{turns}</ul>"))
    if case.get("error"):
        parts.append(_block("error", f'<pre class="error">{_e(case["error"])}</pre>'))
    parts.append(_block("answer", f"<pre>{_e(case['answer'])}</pre>"))
    if case["checks"]:
        items = "".join(
            f'<li><span class="{"pass" if c["pass"] else "fail"}">'
            f"{'pass' if c['pass'] else 'fail'}</span> {_e(c['check'])}"
            f"{': ' + _e(c['detail']) if c.get('detail') else ''}"
            f"{' — ' + _e(c['reason']) if c.get('reason') else ''}</li>"
            for c in case["checks"]
        )
        parts.append(_block("checks", f"<ul>{items}</ul>"))
    retrieval = case.get("retrieval")
    if retrieval:
        bits = []
        if "expected_passage_rank" in retrieval:
            rank = retrieval["expected_passage_rank"]
            bits.append(f"expected passage rank {rank if rank else 'not found'}")
        for key in ("distance", "nearest_distance"):
            if retrieval.get(key) is not None:
                bits.append(f"{key.replace('_', ' ')} {retrieval[key]:.3f}")
        parts.append(_block("retrieval", f"<pre>{_e('; '.join(bits))}</pre>"))
    seen = case.get("seen") or {}
    if seen.get("passages"):
        passages = "".join(f"<li><pre>{_e(p)}</pre></li>" for p in seen["passages"])
        parts.append(
            f'<details><summary class="label">passages the model saw '
            f"({len(seen['passages'])})</summary><ul>{passages}</ul></details>"
        )
    tools = ", ".join(case.get("tools_fired") or []) or "none"
    parts.append(_block("tools fired", f"<pre>{_e(tools)}</pre>"))
    return (
        f'<section class="case" id="case-{_e(case["id"])}" '
        f'data-outcome="{_e(outcome)}">{"".join(parts)}</section>'
    )


def render_html(run: dict) -> str:
    meta = run["run"]
    cases = sorted(run["cases"], key=lambda c: _ORDER.get(c["outcome"], 3))
    title = f"hax eval — {meta['model']} — {meta['started']}"
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title><style>{_CSS}</style></head><body>"
        f"<h1>{_e(title)}</h1>"
        f'<pre class="meta">{_e(render_terminal(run))}</pre>'
        + "".join(_case_html(c) for c in cases)
        + "</body></html>\n"
    )
