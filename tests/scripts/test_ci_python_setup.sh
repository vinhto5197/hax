#!/usr/bin/env bash
# Proves every CI job that runs Python 3.14 sets it up with a retry: the
# first actions/setup-python step carries an id and continue-on-error, and
# the step right after it is an identical
# twin (same action pin, same `with:`) that runs only when the first failed,
# so one flaky Python download does not turn CI red. No other setup-python
# step exists in those jobs. Jobs are discovered from ci.yml (any setup-python
# version starting 3.14) and must include test and e2e; the 3.11 lint job is
# not held to this. The checks bite: mutated copies of ci.yml (twin deleted,
# twin's `with:` differing, continue-on-error missing) are each rejected,
# and a copy whose lint setup changes still passes. Static reads of ci.yml
# only. Run by hand:
#   bash tests/scripts/test_ci_python_setup.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
ci_yml=$root/.github/workflows/ci.yml
work=$(mktemp -d "${TMPDIR:-/tmp}/ci-python-setup-test.XXXXXX")
. "$root/tests/scripts/lib.sh"
trap 'rm -rf "$work"' EXIT

# A python with PyYAML: the venv on a laptop, the system one elsewhere.
py=""
for cand in "$root/.venv/bin/python" python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import yaml' 2>/dev/null; then
    py=$cand
    break
  fi
done

if [ -z "$py" ]; then
  report FAIL "no python with PyYAML found (.venv/bin/python, python3, python): ci.yml checks cannot run"
  echo "$fails failed"
  exit 1
fi

cat > "$work/check.py" <<'PY'
"""Exit 1, printing one reason per line, unless every 3.14 job in the given
workflow sets up Python as a first attempt plus an identical retry."""
import re
import sys

import yaml

SETUP = "actions/setup-python@"
REQUIRED_JOBS = {"test", "e2e"}


def is_setup(step):
    return isinstance(step, dict) and str(step.get("uses", "")).startswith(SETUP)


def version(step):
    return str((step.get("with") or {}).get("python-version", ""))


def check_job(name, steps):
    bad = []
    idx = [i for i, s in enumerate(steps) if is_setup(s)]
    first_i = idx[0]
    first = steps[first_i]
    first_with = first.get("with") or {}
    step_id = first.get("id")

    # The first attempt
    if not step_id:
        bad.append(f"{name}: first setup-python step has no id")
    if first.get("continue-on-error") is not True:
        bad.append(f"{name}: first setup-python step lacks continue-on-error: true")

    # The twin, immediately after
    twin = steps[first_i + 1] if first_i + 1 < len(steps) else None
    if twin is None or not is_setup(twin):
        bad.append(f"{name}: no twin setup-python step immediately after the first")
    else:
        cond = str(twin.get("if", ""))
        want = re.compile(
            r"^\s*(\$\{\{\s*)?steps\.%s\.outcome\s*==\s*'failure'\s*(\}\})?\s*$"
            % re.escape(str(step_id or "<no id>"))
        )
        if not want.match(cond):
            bad.append(f"{name}: twin's if is {cond!r}, not steps.{step_id}.outcome == 'failure'")
        if "continue-on-error" in twin:
            bad.append(f"{name}: twin setup-python step has continue-on-error")
        if (twin.get("with") or {}) != first_with:
            bad.append(f"{name}: twin's with differs: {twin.get('with')!r} vs {first_with!r}")
        if twin.get("uses") != first.get("uses"):
            bad.append(f"{name}: twin uses {twin.get('uses')!r}, first uses {first.get('uses')!r}")

    # No third setup-python
    if len(idx) != 2:
        bad.append(f"{name}: {len(idx)} setup-python steps, want exactly 2")
    return bad


def main(path):
    doc = yaml.safe_load(open(path))
    jobs = doc.get("jobs") or {}
    covered = {}
    for name, job in jobs.items():
        steps = (job or {}).get("steps") or []
        if any(is_setup(s) and version(s).startswith("3.14") for s in steps):
            covered[name] = steps
    bad = []
    missing = REQUIRED_JOBS - covered.keys()
    if missing:
        bad.append(f"discovery: no 3.14 setup-python found in {sorted(missing)}")
    for name, steps in covered.items():
        bad.extend(check_job(name, steps))
    print("covered: " + " ".join(sorted(covered)), file=sys.stderr)
    for b in bad:
        print(b)
    return 1 if bad else 0


sys.exit(main(sys.argv[1]))
PY

cat > "$work/mutate.py" <<'PY'
"""Copy ci.yml with one change to the test job's Python setup, by name.

Exits 3 when the real file does not have the first-plus-twin shape
the mutation needs, so a copy is never built vacuously."""
import sys

import yaml

src, dst, mode = sys.argv[1:4]
doc = yaml.safe_load(open(src))


def setups(job):
    steps = doc["jobs"][job]["steps"]
    return steps, [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/setup-python@")]


if mode == "lint-untouched":
    steps, idx = setups("lint")
    if not idx:
        sys.exit("shape absent: lint has no setup-python step")
    steps[idx[0]]["with"] = {"python-version": "3.11"}
    steps[idx[0]].pop("continue-on-error", None)
else:
    steps, idx = setups("test")
    if len(idx) < 2 or idx[1] != idx[0] + 1:
        print("shape absent: test has no setup-python twin to mutate", file=sys.stderr)
        sys.exit(3)
    first, twin = steps[idx[0]], steps[idx[1]]
    if mode == "no-twin":
        del steps[idx[1]]
    elif mode == "twin-with":
        twin["with"] = {**(twin.get("with") or {}), "python-version": "3.14.7"}
    elif mode == "no-coe":
        first.pop("continue-on-error", None)
    else:
        sys.exit(f"unknown mode {mode}")
yaml.safe_dump(doc, open(dst, "w"), sort_keys=False)
PY

# ── Real file ────────────────────────────────────────────────
if out=$("$py" "$work/check.py" "$ci_yml" 2>"$work/covered"); then
  report PASS "every 3.14 job in ci.yml ($(sed 's/^covered: //' "$work/covered")) has a setup-python and an identical retry"
else
  report FAIL "ci.yml python setup: $(echo "$out" | tr '\n' '|')"
fi

# ── Bites: each copy is rejected for its own change ──────────
bites() {
  local mode=$1 expect=$2 name=$3 out rc=0
  "$py" "$work/mutate.py" "$ci_yml" "$work/ci-$mode.yml" "$mode" 2>"$work/mutate.err" || rc=$?
  if [ "$rc" -ne 0 ]; then
    report FAIL "cannot build a copy with $name: $(tr '\n' ' ' <"$work/mutate.err")"
    return
  fi
  if out=$("$py" "$work/check.py" "$work/ci-$mode.yml" 2>/dev/null); then
    report FAIL "the check passed a ci.yml copy with $name"
  else
    case "$out" in
      *"$expect"*) report PASS "the check rejects a ci.yml copy with $name, naming it" ;;
      *) report FAIL "the check rejected the copy with $name without naming it: $(echo "$out" | tr '\n' '|')" ;;
    esac
  fi
}
bites no-twin "test: no twin setup-python step" "the test job's twin step deleted"
bites twin-with "test: twin's with differs" "the test job's twin on another Python version"
bites no-coe "test: first setup-python step lacks continue-on-error" "continue-on-error missing on the test job's first step"

# ── The lint job is not held to the guard ────────────────────
if "$py" "$work/mutate.py" "$ci_yml" "$work/ci-lint.yml" lint-untouched 2>"$work/mutate.err"; then
  if out=$("$py" "$work/check.py" "$work/ci-lint.yml" 2>/dev/null); then
    report PASS "a copy whose lint setup has no retry still passes"
  else
    report FAIL "a copy with only lint's setup changed fails: $(echo "$out" | tr '\n' '|')"
  fi
else
  report FAIL "cannot build the lint copy: $(tr '\n' ' ' <"$work/mutate.err")"
fi

finish
