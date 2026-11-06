#!/usr/bin/env bash
# Proves `make test ARGS="<pytest args>"` hands ARGS to pytest, so a run can
# be scoped to one file, while a bare `make test` still runs the whole suite
# with nothing extra on the command line. The command-line checks are dry
# runs (make -n) of a copied Makefile; the one real run is a no-DB pytest
# file, made only once the dry run shows ARGS reach pytest (otherwise it
# would run the full, database-backed suite). Run by hand:
#   bash tests/scripts/test_make_test_args.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/make-test-args.XXXXXX")
. "$root/tests/scripts/lib.sh"
trap 'rm -rf "$work"' EXIT

cp "$root/Makefile" "$work/Makefile"
# The pytest line of a dry run, trailing whitespace trimmed.
pytest_line() {
  env -u ARGS MAKEFLAGS= make -s -n -C "$work" test "$@" 2>/dev/null \
    | grep -E '(^|[ /])pytest( |$)' | tail -n 1 | sed -e 's/[[:space:]]*$//'
}

file_args="tests/scripts/test_week_transcript.py -q"

line=$(pytest_line ARGS="$file_args")
case "$line" in
  *"pytest"*" $file_args") report PASS "make test ARGS=... ends the pytest command with ARGS" ;;
  *) report FAIL "make test ARGS=... ends the pytest command with ARGS (got: ${line:-no pytest line})" ;;
esac
case "$line" in
  *"pytest -W error"*) report PASS "make test ARGS=... keeps -W error" ;;
  *) report FAIL "make test ARGS=... keeps -W error (got: ${line:-no pytest line})" ;;
esac
forwarded=0
case "$line" in *" $file_args") forwarded=1 ;; esac

line=$(pytest_line ARGS="-k 'a or b' -x")
case "$line" in
  *"pytest"*" -k 'a or b' -x") report PASS "make test ARGS keeps quoted pytest args intact" ;;
  *) report FAIL "make test ARGS keeps quoted pytest args intact (got: ${line:-no pytest line})" ;;
esac

line=$(pytest_line)
case "$line" in
  *"pytest -W error") report PASS "bare make test runs pytest -W error with no stray args" ;;
  *) report FAIL "bare make test runs pytest -W error with no stray args (got: ${line:-no pytest line})" ;;
esac

if [ "$forwarded" -eq 0 ]; then
  echo "SKIP: real scoped run (ARGS not forwarded; it would run the full suite)"
elif [ ! -x "$root/.venv/bin/pytest" ]; then
  # CI's lint job runs this file with no .venv; the dry runs above still hold.
  echo "SKIP: real scoped run needs .venv (absent here)"
else
  out=$(env -u ARGS MAKEFLAGS= make -s -C "$root" test ARGS="$file_args" 2>&1) && status=0 || status=$?
  if printf '%s' "$out" | grep -qiE 'connection refused|OperationalError|could not connect|ConnectionRefusedError'; then
    echo "SKIP: real scoped run needs Postgres up"
  else
    passed=$(printf '%s' "$out" | grep -oE '[0-9]+ passed' | tail -n 1 | grep -oE '[0-9]+' || true)
    if [ "$status" -eq 0 ] && [ -n "$passed" ] && [ "$passed" -lt 50 ]; then
      report PASS "make test ARGS=<one file> runs only that file's tests ($passed passed)"
    else
      report FAIL "make test ARGS=<one file> runs only that file's tests (exit $status, passed: ${passed:-none})"
    fi
  fi
fi

finish
