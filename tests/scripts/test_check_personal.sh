#!/usr/bin/env bash
# Proves scripts/check_personal.sh: a line ADDED by a change that contains a
# denylisted personal string (whole word, any case) fails the check, which
# names the file and line but never prints the string or the line (CI logs
# are public); lines already in the repo, removed lines and partial-word
# matches pass; with no denylist the check is skipped, never failed. The
# denylist comes from PERSONAL_DENYLIST (CI secret) or the gitignored
# local/personal-denylist.txt. Run by hand:
#   bash tests/scripts/test_check_personal.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
script=$root/scripts/check_personal.sh
work=$(mktemp -d "${TMPDIR:-/tmp}/personal-test.XXXXXX")
fails=0
trap 'rm -rf "$work"' EXIT

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

r=$work/repo
git init -q -b main "$r"
g() { git -C "$r" -c user.email=t@t -c user.name=t "$@"; }
printf 'Jane Roe wrote this once.\n' > "$r/old.txt"
g add -A && g commit -q -m base
export PERSONAL_DENYLIST=$'Jane\nRoe\njane.roe@example.com'

run() { (cd "$r" && "$script" "$@" 2>&1); }

printf 'hello world\n' > "$r/a.txt"; g add a.txt
out=$(run --staged) && report PASS "a clean staged change passes" || report FAIL "clean change failed: $out"

printf 'thanks, jane\n' > "$r/b.txt"; g add b.txt
if out=$(run --staged); then report FAIL "a staged personal name passed"; else report PASS "a staged personal name fails"; fi
case "$out" in *b.txt:1*) report PASS "the failure names the file and line" ;; *) report FAIL "no file:line in: $out" ;; esac
case "$out" in *[Jj]ane*) report FAIL "the output leaks the string: $out" ;; *) report PASS "the output never prints the string" ;; esac
g reset -q b.txt; rm "$r/b.txt"

printf 'see github.com/janeroe/repo\n' > "$r/c.txt"; g add c.txt
out=$(run --staged) && report PASS "a partial-word match passes" || report FAIL "partial word failed: $out"
g reset -q c.txt; rm "$r/c.txt"

printf 'mail jane.roe@example.com\n' > "$r/d.txt"; g add d.txt
if run --staged >/dev/null; then report FAIL "an email passed"; else report PASS "a denylisted email fails"; fi
g reset -q d.txt; rm "$r/d.txt"

g rm -q old.txt
out=$(run --staged) && report PASS "a removed line with the name passes" || report FAIL "removal failed: $out"
g reset -q HEAD old.txt; g checkout -q -- old.txt

g add a.txt && g commit -q -m clean
printf 'Roe was here\n' > "$r/e.txt"; g add e.txt && g commit -q -m leak
if run --range HEAD~2..HEAD >/dev/null; then report FAIL "a committed range with the name passed"; else report PASS "a commit range with the name fails"; fi
out=$(run --range HEAD~2..HEAD~1) && report PASS "a clean range passes" || report FAIL "clean range failed: $out"

out=$(unset PERSONAL_DENYLIST; cd "$r" && "$script" --staged 2>&1) && report PASS "no denylist: skipped, not failed" || report FAIL "no denylist failed: $out"
case "$out" in *skipped*) report PASS "the skip is said" ;; *) report FAIL "silent skip: $out" ;; esac

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
