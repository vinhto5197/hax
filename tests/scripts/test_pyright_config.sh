#!/usr/bin/env bash
# Proves Pyright is wired as a pinned gate: pyproject.toml configures it at
# standard strictness, constraints.txt pins its version, and pre-commit runs
# it as CI does. Static reads of those files only: Pyright itself is never run here
# (the gate's own run is CI's). Run by hand:
#   bash tests/scripts/test_pyright_config.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/tests/scripts/lib.sh"

# A python with tomllib (3.11+) and PyYAML: the venv on a laptop, the system
# one elsewhere.
py=""
for cand in "$root/.venv/bin/python" python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import tomllib, yaml' 2>/dev/null; then
    py=$cand
    break
  fi
done

if [ -z "$py" ]; then
  report FAIL "no python with tomllib and PyYAML found: the config checks cannot run"
else
  # ── [tool.pyright] sets typeCheckingMode = "standard" ──
  mode=$("$py" -c '
import sys, tomllib
d = tomllib.load(open(sys.argv[1], "rb"))
print(d.get("tool", {}).get("pyright", {}).get("typeCheckingMode", ""))
' "$root/pyproject.toml" 2>&1 || true)
  if [ "$mode" = standard ]; then
    report PASS "pyproject.toml's [tool.pyright] sets typeCheckingMode = \"standard\""
  else
    report FAIL "pyproject.toml's [tool.pyright] typeCheckingMode is: ${mode:-unset}"
  fi

  # ── Pre-commit runs Pyright as CI does ─────────────────
  # The whole tree (pass_filenames false), against the venv's packages
  # (--pythonpath), and also when only the pins or the config change: a
  # pin refresh can change Pyright's verdict with no .py file staged.
  # Prints nothing when the hook is right, else what is wrong.
  check_hook() {
    "$py" - "$1" <<'CHK' 2>&1 || true
import re, sys, yaml
d = yaml.safe_load(open(sys.argv[1])) or {}
hooks = [h for r in d.get("repos") or [] for h in r.get("hooks") or [] if h.get("id") == "pyright"]
if not hooks:
    sys.exit(print("no hook with id pyright"))
h = hooks[0]
bad = []
if not str(h.get("entry", "")).split()[-1:] or not str(h.get("entry", "")).split()[-1].endswith("pyright"):
    bad.append(f"entry does not run pyright: {h.get('entry')!r}")
if "--pythonpath" not in [str(a) for a in h.get("args") or []]:
    bad.append("args carry no --pythonpath")
if h.get("pass_filenames") is not False:
    bad.append("pass_filenames is not false")
# pre-commit runs a hook only when files, types/types_or and exclude all
# agree, so a type filter or an exclude can drop the pin and config files.
if h.get("always_run"):
    bad.append("always_run is set: a docs-only commit would run it")
for key in ("types", "types_or", "exclude"):
    if h.get(key):
        bad.append(f"{key} is set: {h.get(key)!r}")
pat = h.get("files")
for path in ("packages/x.py", "packages/x.pyi", "pyproject.toml", "constraints.txt"):
    if not pat or not re.search(pat, path):
        bad.append(f"does not run when only {path} is staged")
if pat and re.search(pat, "README.md"):
    bad.append("runs when only README.md is staged")
print("; ".join(bad))
CHK
  }
  out=$(check_hook "$root/.pre-commit-config.yaml")
  if [ -z "$out" ]; then
    report PASS "pre-commit's pyright hook runs the whole tree with --pythonpath, also on pin and config changes"
  else
    report FAIL "pre-commit's pyright hook: $out"
  fi
  # The check itself bites: broken copies of the hook fail it.
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/pyright-config-test.XXXXXX")
  trap 'rm -rf "$tmp"' EXIT
  sed 's/pass_filenames: false/pass_filenames: true/' "$root/.pre-commit-config.yaml" > "$tmp/staged-only.yaml"
  case "$(check_hook "$tmp/staged-only.yaml")" in
    *"pass_filenames"*) report PASS "the hook check fails a copy whose pyright hook gets only the staged files" ;;
    *) report FAIL "the hook check passes a copy with pass_filenames: true" ;;
  esac
  "$py" - "$root/.pre-commit-config.yaml" "$tmp/py-only.yaml" <<'CPY' || report FAIL "could not write the py-only copy"
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
for r in d["repos"]:
    for h in r.get("hooks") or []:
        if h.get("id") == "pyright":
            h["types"] = ["python"]
yaml.safe_dump(d, open(sys.argv[2], "w"))
CPY
  case "$(check_hook "$tmp/py-only.yaml")" in
    *"types is set"*) report PASS "the hook check fails a copy whose pyright hook runs only when a .py file is staged" ;;
    *) report FAIL "the hook check passes a copy that runs only on .py files" ;;
  esac
fi

# ── constraints.txt pins pyright==1.1.407 ────────────────
if grep -Eiq '^pyright==1\.1\.407([[:space:]]|$)' "$root/constraints.txt"; then
  report PASS "constraints.txt pins pyright==1.1.407"
else
  report FAIL "constraints.txt pins: $(grep -Ei '^pyright' "$root/constraints.txt" || echo 'no pyright line')"
fi

finish
