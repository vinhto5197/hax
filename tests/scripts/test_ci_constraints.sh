#!/usr/bin/env bash
# Proves CI installs Python packages only at the versions in
# ci-constraints.txt (refreshed on purpose by `make constraints`), so an
# upstream release cannot turn CI red overnight: every `pip install -e` in the
# workflow passes `-c ci-constraints.txt`, and the file pins exact versions,
# including the two that broke CI on 2026-10-28. Run by hand:
#   bash tests/scripts/test_ci_constraints.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
ci=$root/.github/workflows/ci.yml
pins=$root/ci-constraints.txt
fails=0

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

[ -f "$pins" ] && report PASS "the constraints file exists" || report FAIL "no ci-constraints.txt"

installs=$(grep -E 'pip install -e' "$ci" || true)
[ -n "$installs" ] && report PASS "CI installs the project with pip" || report FAIL "no pip install -e in ci.yml"
unconstrained=$(printf '%s\n' "$installs" | grep -v -- '-c ci-constraints.txt' || true)
[ -z "$unconstrained" ] && report PASS "every project install is constrained" || report FAIL "unconstrained install: $unconstrained"

if [ -f "$pins" ]; then
  loose=$(grep -vE '^(#|$)' "$pins" | grep -vE '^[A-Za-z0-9._-]+(\[[^]]*\])?==[^=]+$' || true)
  [ -z "$loose" ] && report PASS "every line pins an exact version" || report FAIL "not an exact pin: $loose"
  for pkg in langsmith pytest-asyncio pytest; do
    grep -qiE "^${pkg}==" "$pins" && report PASS "$pkg is pinned" || report FAIL "$pkg is not pinned"
  done
fi

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
