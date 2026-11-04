#!/usr/bin/env bash
# Proves `make ci` and CI share one set of commands: the ci-* targets carry
# exactly CI's checks, `make ci` runs them in CI's order, and ci.yml's check
# steps are make calls (a guard over ci.yml, shown here to bite on a copy
# with a stray check step), so the local run cannot drift from CI.
# Dry runs (make -n), static reads of ci.yml, and one real types-check
# against a stub python: no suite runs, and local/.gate.lock is never
# touched; ci-test also carries the Pyright gate and types-check runs it
# alone. Run by hand:
#   bash tests/scripts/test_make_ci.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
ci_yml=$root/.github/workflows/ci.yml
work=$(mktemp -d "${TMPDIR:-/tmp}/make-ci-test.XXXXXX")
fails=0
trap 'rm -rf "$work"' EXIT

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

# Every dry run starts from a clean make environment: run inside `make
# ci-lint RUFF=ruff` (CI), the parent's overrides reach a nested make through
# MAKEFLAGS and would replace the defaults under test.
clean_make() {
  env -u MAKEFLAGS -u MFLAGS -u MAKELEVEL -u MAKEOVERRIDES -u GNUMAKEFLAGS \
    -u RUFF -u PY -u BASE make "$@"
}
dry() { clean_make -s -n -C "$root" "$@" 2>&1; }

# A python with PyYAML: the venv on a laptop, the system one elsewhere.
py=""
for cand in "$root/.venv/bin/python" python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import yaml' 2>/dev/null; then
    py=$cand
    break
  fi
done

# ── M1: every ci target dry-runs ─────────────────────────────
for target in ci-lint ci-test ci-web ci; do
  if out=$(dry "$target"); then
    report PASS "make -n $target exits 0"
  else
    report FAIL "make -n $target failed: $(echo "$out" | tail -n 3)"
  fi
done

# ── M2: make ci runs lint, test, web, e2e in that order ──────
ci_out=$(dry ci || true)
line_of() { echo "$ci_out" | grep -n -F -- "$1" | head -n 1 | cut -d: -f1 || true; }
l_lint=$(line_of "ruff check .")
l_test=$(line_of "pytest -W error")
l_web=$(line_of "tsc --noEmit")
l_e2e=$(line_of "playwright test")
if [ -n "$l_lint" ] && [ -n "$l_test" ] && [ -n "$l_web" ] && [ -n "$l_e2e" ] \
  && [ "$l_lint" -lt "$l_test" ] && [ "$l_test" -lt "$l_web" ] && [ "$l_web" -lt "$l_e2e" ]; then
  report PASS "make ci names ci-lint, ci-test, ci-web, e2e steps in that order"
else
  report FAIL "make ci order (line of lint=${l_lint:-none} test=${l_test:-none} web=${l_web:-none} e2e=${l_e2e:-none})"
fi

# ── M3-M5: each target carries its job's checks ──────────────
contains_all() {
  local target=$1
  shift
  local out missing=""
  out=$(dry "$target" || true)
  for needle in "$@"; do
    case "$out" in
      *"$needle"*) ;;
      *) missing="$missing [$needle]" ;;
    esac
  done
  if [ -z "$missing" ]; then
    report PASS "make -n $target carries every check of its CI job"
  else
    report FAIL "make -n $target is missing:$missing"
  fi
}
contains_all ci-lint "check_personal.sh --range" "ruff check ." "ruff format --check ." \
  "tests/scripts/" "node --test tests/workflows/feature-chain.test.mjs" \
  "caddy validate" "compose.prod.yml config -q"
contains_all ci-test "check_constraints.sh constraints.txt" "pytest -W error" \
  "export_openapi" "generate:types" "git diff --exit-code -- lib/openapi.ts"
contains_all ci-web "tsc --noEmit" "npm run lint" "npm test" "prettier@3.3.3 --check"

# ── M6: ci-test's pytest runs under the gate lock only where local/ exists ──
cp "$root/Makefile" "$work/Makefile"
dry_copy() { clean_make -s -n -C "$work" "$@" 2>/dev/null || true; }
mkdir -p "$work/local"
pytest_line=$(dry_copy ci-test | grep -F "pytest -W error" | head -n 1 || true)
case "$pytest_line" in
  *"with-lock.sh local/.gate.lock"*) report PASS "ci-test runs pytest under the gate lock on a configured machine" ;;
  *) report FAIL "ci-test ran pytest unlocked with local/ present: ${pytest_line:-no pytest line}" ;;
esac
rm -rf "$work/local"
out=$(dry_copy ci-test)
case "$out" in
  *"pytest -W error"*)
    case "$out" in
      *"with-lock.sh"*) report FAIL "ci-test locked with no local/ (CI would fail)" ;;
      *) report PASS "ci-test runs pytest unlocked without local/" ;;
    esac ;;
  *) report FAIL "ci-test without local/ names no pytest -W error" ;;
esac

# ── M7: PY and RUFF override the .venv paths ─────────────────
override_ok=1
out=$(dry PY=python RUFF=ruff ci-lint ci-test) || override_ok=0
case "$override_ok:$out" in
  0:*) report FAIL "make -n PY=python RUFF=ruff ci-lint ci-test failed: $(echo "$out" | tail -n 1)" ;;
  *".venv/bin/"*) report FAIL "PY=python RUFF=ruff still uses a .venv path: $(echo "$out" | grep -F .venv/bin/ | head -n 1)" ;;
  *) report PASS "PY=python RUFF=ruff leaves no .venv path in ci-lint and ci-test" ;;
esac
if echo "$out" | grep -Eq '(^|[[:space:];&|(])ruff check \.' \
  && echo "$out" | grep -Eq '(^|[[:space:];&|(])ruff format --check \.' \
  && echo "$out" | grep -Eq '(^|[[:space:];&|(])python -m pytest -W error'; then
  report PASS "PY=python RUFF=ruff runs ruff and python by those names"
else
  report FAIL "PY=python RUFF=ruff does not run plain ruff check/format and python -m pytest"
fi
out=$(dry ci-lint ci-test || true)
case "$out" in
  *".venv/bin/ruff check ."*".venv/bin/python"*) report PASS "the defaults are .venv/bin/ruff and .venv/bin/python" ;;
  *) report FAIL "the defaults do not use .venv/bin/ruff then .venv/bin/python" ;;
esac

# ── T3: ci-test runs pyright after the pin check, before pytest ──
out=$(dry ci-test || true)
l_of() { echo "$out" | grep -n -F -- "$1" | head -n 1 | cut -d: -f1 || true; }
l_pin=$(l_of "check_constraints.sh constraints.txt")
l_pyright=$(l_of "-m pyright")
l_pytest=$(l_of "pytest -W error")
if [ -n "$l_pin" ] && [ -n "$l_pyright" ] && [ -n "$l_pytest" ] \
  && [ "$l_pin" -lt "$l_pyright" ] && [ "$l_pyright" -lt "$l_pytest" ]; then
  report PASS "make -n ci-test runs -m pyright after the pin check and before pytest"
else
  report FAIL "ci-test pyright order (line of pin=${l_pin:-none} pyright=${l_pyright:-none} pytest=${l_pytest:-none})"
fi

# ── T4: make types-check runs pyright locally ────────────────
if out=$(dry types-check); then
  case "$out" in
    *pyright*) report PASS "make -n types-check exits 0 and runs pyright" ;;
    *) report FAIL "make -n types-check names no pyright: $(echo "$out" | tail -n 3)" ;;
  esac
else
  report FAIL "make -n types-check failed: $(echo "$out" | tail -n 3)"
fi

# ── T4b: a bare PY (CI's PY=python) reaches Pyright as a path ──
# Pyright joins a bare --pythonpath to the current folder instead of looking
# it up on PATH, and then every third-party import reads as missing. A real
# run with a stub python first on PATH: the stub records Pyright's arguments.
stub=$work/stub-bin
mkdir -p "$stub"
cat > "$stub/python" <<STUB
#!/bin/sh
if [ "\$1" = -m ] && [ "\$2" = pyright ]; then
  printf '%s\n' "\$@" > "$work/pyright-args"
  exit 0
fi
exec python3 "\$@"
STUB
chmod +x "$stub/python"
if PATH="$stub:$PATH" clean_make -s -C "$root" types-check PY=python >/dev/null 2>&1; then
  pp=$(grep -A1 -x -- --pythonpath "$work/pyright-args" 2>/dev/null | tail -n 1 || true)
  case "$pp" in
    /*) report PASS "make types-check PY=python hands Pyright an absolute --pythonpath" ;;
    *) report FAIL "make types-check PY=python hands Pyright --pythonpath '${pp:-none}', not a path" ;;
  esac
else
  report FAIL "make types-check PY=python failed with the stub python"
fi

# ── M8/M9: ci.yml, parsed ────────────────────────────────────
if [ -z "$py" ]; then
  report FAIL "no python with PyYAML found (.venv/bin/python, python3, python): ci.yml checks cannot run"
else
  cat > "$work/guard.py" <<'PY'
"""Exit 1 when a check job in ci.yml runs anything but make or setup.

Every job but build and deploy is a check job; one not named here fails.
"""
import re
import sys

import yaml

CHECK_JOBS = {"lint": "ci-lint", "test": "ci-test", "web": "ci-web", "e2e": "e2e"}
MAKE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*=\S*\s+)*make(\s|$)")
SETUP = [
    re.compile(r"^(\S*/)?pip3? install(\s|$)"),
    re.compile(r"^(\S*/)?python3? -m pip install(\s|$)"),
    re.compile(r"^(\S*/)?python3? -m venv(\s|$)"),
    re.compile(r"^npm ci(\s|$)"),
    re.compile(r"^npx playwright install(\s|$)"),
    re.compile(r"""^echo "version=\$\(npx playwright --version"""),
    re.compile(r"^cd \S+$"),
]
# The Playwright version probe pipes inside $(...): allowed whole, before
# the line is split on shell operators.
PROBE = re.compile(
    r"""^echo "version=\$\(npx playwright --version \| awk '\{print \$2\}'\)" >> "\$GITHUB_OUTPUT"$"""
)
USES = re.compile(r"^actions/(checkout|setup-python|setup-node|cache|upload-artifact)@")
UNCHECKED_JOBS = {"build", "deploy"}


def commands(run):
    text = re.sub(r"\\\n", " ", run)
    for line in text.splitlines():
        if PROBE.match(line.strip()):
            continue
        for part in re.split(r"&&|\|\||\||;", line):
            part = part.strip()
            if part and not part.startswith("#"):
                yield part


def main(path):
    doc = yaml.safe_load(open(path))
    jobs = doc.get("jobs", {})
    bad = []
    for job in jobs:
        if job not in CHECK_JOBS and job not in UNCHECKED_JOBS:
            bad.append(f"{job}: unknown job, not a make target")
    for job, target in CHECK_JOBS.items():
        steps = (jobs.get(job) or {}).get("steps") or []
        if not steps:
            bad.append(f"{job}: job missing or has no steps")
            continue
        calls_target = False
        for step in steps:
            uses = step.get("uses")
            if uses is not None and not USES.match(str(uses)):
                bad.append(f"{job}: action not allowed: {uses}")
            run = step.get("run")
            if run is None:
                continue
            for cmd in commands(str(run)):
                if MAKE.match(cmd):
                    if re.search(rf"(\s){re.escape(target)}(\s|$)", cmd):
                        calls_target = True
                elif not any(p.match(cmd) for p in SETUP):
                    bad.append(f"{job}: not make or setup: {cmd}")
        if not calls_target:
            bad.append(f"{job}: never calls make {target}")
    for b in bad:
        print(b)
    return 1 if bad else 0


sys.exit(main(sys.argv[1]))
PY
  cat > "$work/mutate.py" <<'PY'
"""Copy ci.yml with one guard-breaking change, picked by name."""
import sys

import yaml

src, dst, mode = sys.argv[1:4]
doc = yaml.safe_load(open(src))
lint = doc["jobs"]["lint"]["steps"]
if mode == "stray-step":
    lint.append({"name": "Stray check", "run": "ruff check ."})
elif mode == "new-job":
    doc["jobs"]["extra"] = {"runs-on": "ubuntu-latest", "steps": [{"run": "make ci-lint"}]}
elif mode == "pipe":
    lint.append({"name": "Piped", "run": "pip install x | ruff check ."})
elif mode == "or":
    lint.append({"name": "Or", "run": "pip install x || ruff check ."})
elif mode == "action":
    lint.append({"uses": "astral-sh/ruff-action@v3"})
yaml.safe_dump(doc, open(dst, "w"), sort_keys=False)
PY

  if out=$("$py" "$work/guard.py" "$ci_yml" 2>&1); then
    report PASS "every run step in ci.yml's lint, test, web, e2e jobs is a make call or setup"
  else
    report FAIL "ci.yml guard: $(echo "$out" | tr '\n' '|')"
  fi

  # Each copy must fail the guard with the line naming its own change, so a
  # failure for some other reason does not count.
  bites() {
    local mode=$1 expect=$2 name=$3 out
    "$py" "$work/mutate.py" "$ci_yml" "$work/ci-$mode.yml" "$mode"
    if out=$("$py" "$work/guard.py" "$work/ci-$mode.yml" 2>&1); then
      report FAIL "the guard passed a ci.yml copy with $name"
    else
      case "$out" in
        *"$expect"*) report PASS "the guard fails a ci.yml copy with $name, naming it" ;;
        *) report FAIL "the guard failed the copy with $name without naming it: $out" ;;
      esac
    fi
  }
  bites stray-step "lint: not make or setup: ruff check ." "a stray non-make check step"
  bites new-job "extra: unknown job" "a new job outside lint, test, web, e2e, build, deploy"
  bites pipe "lint: not make or setup: ruff check ." "a check piped after a setup command"
  bites or "lint: not make or setup: ruff check ." "a check after || behind a setup command"
  bites action "lint: action not allowed: astral-sh/ruff-action@v3" "a uses: step outside the allowed actions"

  needs=$("$py" -c '
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
print(" ".join(sorted(d["jobs"]["deploy"].get("needs") or [])))
' "$ci_yml" 2>&1 || true)
  if [ "$needs" = "e2e lint test web" ]; then
    report PASS "the deploy job still needs lint, test, web and e2e"
  else
    report FAIL "the deploy job needs: ${needs:-nothing}"
  fi
fi

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
