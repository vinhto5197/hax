#!/usr/bin/env bash
# Proves Pyright is wired as a pinned gate: pyproject.toml configures it at
# standard strictness, constraints.txt pins its version, and pre-commit runs
# it. Static reads of those files only: Pyright itself is never run here
# (the gate's own run is CI's). Run by hand:
#   bash tests/scripts/test_pyright_config.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
fails=0

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

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
  # ── T5: [tool.pyright] sets typeCheckingMode = "standard" ──
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

  # ── T7: .pre-commit-config.yaml has a hook with id pyright ──
  ids=$("$py" -c '
import sys, yaml
d = yaml.safe_load(open(sys.argv[1])) or {}
print(" ".join(str(h.get("id")) for r in d.get("repos") or [] for h in r.get("hooks") or []))
' "$root/.pre-commit-config.yaml" 2>&1 || true)
  case " $ids " in
    *" pyright "*) report PASS ".pre-commit-config.yaml has a hook with id pyright" ;;
    *) report FAIL ".pre-commit-config.yaml has no pyright hook (ids: ${ids:-none})" ;;
  esac
fi

# ── T6: constraints.txt pins pyright==1.1.407 ────────────────
if grep -Eiq '^pyright==1\.1\.407([[:space:]]|$)' "$root/constraints.txt"; then
  report PASS "constraints.txt pins pyright==1.1.407"
else
  report FAIL "constraints.txt pins: $(grep -Ei '^pyright' "$root/constraints.txt" || echo 'no pyright line')"
fi

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
