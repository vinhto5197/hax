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
. "$root/tests/scripts/lib.sh"
trap 'rm -rf "$work"' EXIT

printf '# header\nfastapi==0.141.1\nlangsmith==0.14.14\nPyYAML==6.0.3\npydantic-core==2.23.4\nruamel.yaml==0.18.6\n' > "$work/constraints.txt"

out=$(printf 'fastapi==0.141.1\nlangsmith==0.14.14\npyyaml==6.0.3\n-e git+https://x#egg=hax\n' | "$check" "$work/constraints.txt" 2>&1) \
  && report PASS "everything pinned passes (names compared case- and separator-insensitively)" \
  || report FAIL "pinned set failed: $out"

out=$(printf 'pydantic_core==2.23.4\nruamel-yaml==0.18.6\n' | "$check" "$work/constraints.txt" 2>&1) \
  && report PASS "'-', '_' and '.' in a name compare equal" \
  || report FAIL "separator-normalised names failed: $out"

out=$(printf 'fastapi==0.141.1\n' | "$check" "$work/constraints.txt" 2>&1) \
  && report PASS "a pin for a package that is not installed does not fail" \
  || report FAIL "a lock entry not installed failed: $out"

out=$(printf 'fastapi==0.141.1\nlangsmith==0.14.14\nnew-thing==1.0\n' | "$check" "$work/constraints.txt" 2>&1) \
  && report FAIL "an unpinned package passed" \
  || case "$out" in *"new-thing"*"make constraints"*) report PASS "an unpinned package fails, named, with the fix" ;; *) report FAIL "unpinned message: $out" ;; esac

case "$out" in
  *fastapi*|*langsmith*) report FAIL "the unpinned failure also names pinned packages: $out" ;;
  *) report PASS "the unpinned failure names only the unpinned package" ;;
esac

out=$(printf 'fastapi==0.141.1\nlangsmith==0.15.0\n' | "$check" "$work/constraints.txt" 2>&1) \
  && report FAIL "a version off its pin passed" \
  || case "$out" in *"langsmith"*) report PASS "a version off its pin fails" ;; *) report FAIL "drift message: $out" ;; esac

out=$(printf 'fastapi==0.141.1\n' | "$check" "$work/missing.txt" 2>&1) \
  && report FAIL "a missing constraints file passed" \
  || report PASS "a missing constraints file fails"

out=$("$check" < /dev/null 2>&1) \
  && report FAIL "no constraints-file argument passed" \
  || report PASS "no constraints-file argument fails"

# Direct-URL freeze lines (`name @ <url>`) are not pinned releases, whatever
# constraints.txt says about the name. Offenders are named on stderr.
printf 'fastapi==0.141.1\nmylib==1.0\nother==1.0\n' > "$work/url-constraints.txt"

rc=0; printf 'fastapi==0.141.1\nmylib @ git+https://example.com/mylib.git@abc123\n' \
  | "$check" "$work/url-constraints.txt" >/dev/null 2>"$work/err" || rc=$?
[ "$rc" -eq 1 ] && grep -q 'mylib' "$work/err" \
  && report PASS "a git direct-URL line fails, naming it on stderr, even when its name is pinned" \
  || report FAIL "git direct-URL line: exit $rc, stderr: $(cat "$work/err")"

rc=0; printf 'fastapi==0.141.1\nother @ file:///tmp/other-1.0.tar.gz\n' \
  | "$check" "$work/url-constraints.txt" >/dev/null 2>"$work/err" || rc=$?
[ "$rc" -eq 1 ] && grep -q 'other' "$work/err" \
  && report PASS "a file direct-URL line fails, naming it on stderr" \
  || report FAIL "file direct-URL line: exit $rc, stderr: $(cat "$work/err")"

rc=0; printf 'fastapi==0.141.1\nmylib @ git+https://example.com/mylib.git@abc123\n' \
  | "$check" "$work/url-constraints.txt" >/dev/null 2>"$work/err" || rc=$?
grep -q 'fastapi' "$work/err" \
  && report FAIL "the direct-URL failure also names a pinned package: $(cat "$work/err")" \
  || report PASS "the direct-URL failure names only the direct-URL package"

rc=0; out=$(printf 'FastAPI==0.141.1\npydantic.core==2.23.4\nRuamel_YAML==0.18.6\npyyaml==6.0.3\n' \
  | "$check" "$work/constraints.txt" 2>&1) || rc=$?
[ "$rc" -eq 0 ] && [ "$(printf '%s\n' "$out" | grep -c .)" -eq 1 ] \
  && report PASS "a clean freeze with mixed case and separators exits 0 with a one-line summary" \
  || report FAIL "clean mixed-name freeze: exit $rc, output: $out"

rc=0; printf 'fastapi==0.141.1\nnot-pinned==2.0\n' \
  | "$check" "$work/constraints.txt" >/dev/null 2>"$work/err" || rc=$?
[ "$rc" -eq 1 ] && grep -q 'not-pinned' "$work/err" \
  && report PASS "an unpinned package exits 1, named on stderr" \
  || report FAIL "unpinned package: exit $rc, stderr: $(cat "$work/err")"

rc=0; printf 'fastapi==0.141.1\nPyYAML==6.0.2\n' \
  | "$check" "$work/constraints.txt" >/dev/null 2>"$work/err" || rc=$?
[ "$rc" -eq 1 ] && grep -qi 'pyyaml' "$work/err" \
  && report PASS "a package off its pinned version exits 1, named on stderr" \
  || report FAIL "version drift: exit $rc, stderr: $(cat "$work/err")"

rc=0; out=$(printf '\n# Editable install with no version control (hax==0.1.0)\nfastapi==0.141.1\n\n#another comment\nlangsmith==0.14.14\n\n' \
  | "$check" "$work/constraints.txt" 2>&1) || rc=$?
[ "$rc" -eq 0 ] \
  && report PASS "blank lines and '#' comment lines in the freeze are ignored" \
  || report FAIL "comments/blank lines: exit $rc, output: $out"

finish
