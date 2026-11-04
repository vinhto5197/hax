#!/usr/bin/env bash
# Proves scripts/explorer.sh: the committed upload fixture is a real text file
# and the runner copies it into the run's own directory, where its prompt names
# it; `--check` treats a .running naming a
# dead pid as a run that is over, not one still going. --check runs against a
# copy of the script in a temp project (a git repo of its own) with
# CLAUDE_PROJECT_DIR pointed at it, so the real local/explorer/ is never read
# or written and no stack is started.
# Run by hand:
#   bash tests/scripts/test_explorer.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
script=$root/scripts/explorer.sh
work=$(mktemp -d "${TMPDIR:-/tmp}/explorer-test.XXXXXX")
fails=0
live_pid=
cleanup() { [ -n "$live_pid" ] && kill "$live_pid" 2>/dev/null; rm -rf "$work"; }
trap cleanup EXIT

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

# (E1) Grep-level, never a run. The committed fixture is a non-empty text
# file; the prompt's "The file to upload:" path sits under the run's own
# directory ($run_dir, which the browser tool may read from); and a cp or
# install line copies the committed fixture to that same path. Quotes and
# ${var} braces are normalized away before comparing.
norm() { printf '%s' "$1" | sed -e 's/["'\'']//g' -e 's/\${\([A-Za-z_][A-Za-z0-9_]*\)}/$\1/g' -e 's/[[:space:]]*$//'; }
fixture_rel=.claude/skills/product-explorer/fixture.txt
fixture=$root/$fixture_rel
if [ -f "$fixture" ] && [ -s "$fixture" ] && grep -qI . "$fixture"; then
  report PASS "the committed upload fixture is a non-empty text file"
else
  report FAIL "the committed upload fixture is a non-empty text file: '$fixture_rel' missing, empty or not text"
fi

line=$(grep -m1 'The file to upload:' "$script" || true)
upload=$(norm "${line#*The file to upload: }")
case "$upload" in
  '$run_dir/'?*) report PASS "the prompt's upload path is under the run's own directory" ;;
  *) report FAIL "the prompt's upload path is under the run's own directory: got '${upload:-<no line>}'" ;;
esac

copied=no
while IFS= read -r cpline; do
  n=$(norm "$cpline")
  case "$n" in
    *"$fixture_rel"*) ;;
    *) continue ;;
  esac
  rest=${n#*"$fixture_rel"}
  case " $rest " in
    *[[:space:]]"$upload"[[:space:]]*) copied=yes ;;
  esac
done < <(grep -E '(^|[^A-Za-z_])(cp|install)[[:space:]]' "$script" | grep 'fixture\.txt' || true)
if [ -n "$upload" ] && [ "$copied" = yes ]; then
  report PASS "the runner copies the committed fixture to the path the prompt names"
else
  report FAIL "the runner copies the committed fixture to the path the prompt names: no cp/install of $fixture_rel to '${upload:-<none>}'"
fi
# (E2) --check against a temp project. A live pid in .running is the control:
# it proves --check reaches the already-running test in this setup, so the
# dead-pid case cannot pass vacuously.
proj=$work/proj
mkdir -p "$proj/scripts" "$proj/.claude/skills" "$proj/local/explorer"
cp "$script" "$proj/scripts/explorer.sh"
cp -R "$root/.claude/skills/product-explorer" "$proj/.claude/skills/"
git -C "$proj" init -q

check() {
  CLAUDE_PROJECT_DIR="$proj" DUE_TODAY=2026-11-06 timeout 60 \
    bash "$proj/scripts/explorer.sh" --check 2>&1 || true
}

sleep 120 &
live_pid=$!
echo "$live_pid" > "$proj/local/explorer/.running"
out=$(check)
if printf '%s' "$out" | grep -qi 'already running'; then
  report PASS "--check with a live pid in .running answers already running (control)"
else
  report FAIL "--check with a live pid in .running answers already running (control): got '$out'"
fi

sh -c 'exit 0' &
dead_pid=$!
wait "$dead_pid" 2>/dev/null || true
if kill -0 "$dead_pid" 2>/dev/null; then
  report FAIL "--check with a dead pid in .running does not answer already running: pid $dead_pid was reused"
else
  echo "$dead_pid" > "$proj/local/explorer/.running"
  out=$(check)
  if printf '%s' "$out" | grep -qi 'already running'; then
    report FAIL "--check with a dead pid in .running does not answer already running: got '$out'"
  else
    report PASS "--check with a dead pid in .running does not answer already running"
  fi
fi

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
