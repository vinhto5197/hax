#!/usr/bin/env bash
# Proves scripts/check_constraints.sh: after an install, every installed
# package (the project itself excepted) must be pinned in constraints.txt, so
# a dependency added without `make constraints` fails CI instead of
# installing unpinned. It reads `pip freeze` output on stdin. Run by hand:
#   bash tests/scripts/test_check_constraints.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
check=$root/scripts/check_constraints.sh
work=$(mktemp -d "${TMPDIR:-/tmp}/check-constraints-test.XXXXXX")
fails=0
trap 'rm -rf "$work"' EXIT

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

printf '# header\nfastapi==0.141.1\nlangsmith==0.14.14\nPyYAML==6.0.3\n' > "$work/constraints.txt"

out=$(printf 'fastapi==0.141.1\nlangsmith==0.14.14\npyyaml==6.0.3\n-e git+https://x#egg=hax\n' | "$check" "$work/constraints.txt" 2>&1) \
  && report PASS "everything pinned passes (names compared case- and separator-insensitively)" \
  || report FAIL "pinned set failed: $out"

out=$(printf 'fastapi==0.141.1\nlangsmith==0.14.14\nnew-thing==1.0\n' | "$check" "$work/constraints.txt" 2>&1) \
  && report FAIL "an unpinned package passed" \
  || case "$out" in *"new-thing"*"make constraints"*) report PASS "an unpinned package fails, named, with the fix" ;; *) report FAIL "unpinned message: $out" ;; esac

out=$(printf 'fastapi==0.141.1\nlangsmith==0.15.0\n' | "$check" "$work/constraints.txt" 2>&1) \
  && report FAIL "a version off its pin passed" \
  || case "$out" in *"langsmith"*) report PASS "a version off its pin fails" ;; *) report FAIL "drift message: $out" ;; esac

out=$(printf 'fastapi==0.141.1\n' | "$check" "$work/missing.txt" 2>&1) \
  && report FAIL "a missing constraints file passed" \
  || report PASS "a missing constraints file fails"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
