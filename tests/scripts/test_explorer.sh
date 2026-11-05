#!/usr/bin/env bash
# Proves scripts/explorer.sh: the committed upload fixture is a real text file
# and the runner copies it into the run's own directory, where its prompt names
# it; `--check` treats a .running naming a
# dead pid as a run that is over, not one still going; a full run whose check
# fails records this week as failed with the check's reason in .status.json
# (the due hook reads it), except that an already-running failure leaves the
# live run's status untouched and a check failure keeps this week's "done"
# (still exiting 1). --check and full runs go against a
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

# (E3) A full run whose check fails writes this week's status before exiting.
# The temp project has local/, the persona files and no .running, but no root
# .env, so the check's first failure is the .env one (the reason is asserted to
# name it, so a failure earlier in the order cannot pass). The stale status is
# last week's "done": the due hook stays silent all week if it survives.
# DUE_TODAY=2026-11-06 is a Friday in ISO week 2026-W45.
status=$proj/local/explorer/.status.json
json_field() {
  python3 -c 'import json,sys
v = json.load(open(sys.argv[1])).get(sys.argv[2])
print("" if v is None else v)' "$1" "$2" 2>/dev/null || echo "<unreadable>"
}
full_run() {
  CLAUDE_PROJECT_DIR="$proj" DUE_TODAY=2026-11-06 timeout 60 \
    bash "$proj/scripts/explorer.sh" >"$work/full.out" 2>&1
}

rm -f "$proj/local/explorer/.running"
cat > "$status" <<'EOF'
{"week": "2026-W44", "persona": "stale", "state": "done", "reason": "", "notes": "", "logs": "", "started": "2026-10-30T09:00:00Z", "updated": "2026-10-30T10:00:00Z"}
EOF
rc=0
full_run || rc=$?
week=$(json_field "$status" week)
state=$(json_field "$status" state)
reason=$(json_field "$status" reason)
if [ "$rc" -eq 1 ]; then
  report PASS "a full run with no .env exits 1"
else
  report FAIL "a full run with no .env exits 1: exit $rc, output '$(cat "$work/full.out")'"
fi
if [ "$week" = 2026-W45 ] && [ "$state" = failed ]; then
  report PASS "a full run whose check fails records this week as failed"
else
  report FAIL "a full run whose check fails records this week as failed: week '$week', state '$state'"
fi
case "$reason" in
  *.env*) report PASS "the recorded failure reason is the check's (.env)" ;;
  *) report FAIL "the recorded failure reason is the check's (.env): got '$reason'" ;;
esac

# (E4) A full run that finds a live run leaves that run's status byte-identical:
# the failed check is "already running", and the live run owns .status.json.
# A fresh sleeper, so the earlier one's age cannot matter.
kill "$live_pid" 2>/dev/null || true
wait "$live_pid" 2>/dev/null || true
sleep 120 &
live_pid=$!
echo "$live_pid" > "$proj/local/explorer/.running"
cat > "$status" <<'EOF'
{"week": "2026-W45", "persona": "live", "state": "running", "reason": "", "notes": "", "logs": "", "started": "2026-11-06T09:00:00Z", "updated": "2026-11-06T09:05:00Z"}
EOF
cp "$status" "$work/status.before"
rc=0
full_run || rc=$?
if [ "$rc" -ne 0 ] && grep -qi 'already running' "$work/full.out" \
  && cmp -s "$work/status.before" "$status"; then
  report PASS "a full run during a live run leaves the live run's status untouched"
else
  report FAIL "a full run during a live run leaves the live run's status untouched: exit $rc, output '$(cat "$work/full.out")', status '$(cat "$status" 2>/dev/null)'"
fi
kill "$live_pid" 2>/dev/null || true
wait "$live_pid" 2>/dev/null || true
live_pid=

# (E5) A check failure keeps this week's "done" byte-identical: the week's run
# already happened, so a later failed attempt must not unrecord it. Same
# failing check as E3 (no root .env, no .running).
rm -f "$proj/local/explorer/.running"
cat > "$status" <<'EOF'
{"week": "2026-W45", "persona": "done-persona", "state": "done", "reason": "", "notes": "three findings filed", "logs": "", "started": "2026-11-06T09:00:00Z", "updated": "2026-11-06T10:00:00Z"}
EOF
cp "$status" "$work/status.before"
rc=0
full_run || rc=$?
if [ "$rc" -eq 1 ]; then
  report PASS "a full run with no .env after this week's done exits 1"
else
  report FAIL "a full run with no .env after this week's done exits 1: exit $rc, output '$(cat "$work/full.out")'"
fi
if cmp -s "$work/status.before" "$status"; then
  report PASS "a full run whose check fails keeps this week's done status byte-identical"
else
  report FAIL "a full run whose check fails keeps this week's done status byte-identical: status '$(cat "$status" 2>/dev/null)'"
fi
if grep -q '\.env' "$work/full.out"; then
  report PASS "a full run after this week's done still names the check's reason (.env)"
else
  report FAIL "a full run after this week's done still names the check's reason (.env): output '$(cat "$work/full.out")'"
fi

# (E6) With no status file at all, a check failure records this week as failed.
rm -f "$proj/local/explorer/.running" "$status"
rc=0
full_run || rc=$?
week=$(json_field "$status" week)
state=$(json_field "$status" state)
if [ "$rc" -eq 1 ]; then
  report PASS "a full run with no .env and no status file exits 1"
else
  report FAIL "a full run with no .env and no status file exits 1: exit $rc, output '$(cat "$work/full.out")'"
fi
if [ "$week" = 2026-W45 ] && [ "$state" = failed ]; then
  report PASS "a full run whose check fails with no status file records this week as failed"
else
  report FAIL "a full run whose check fails with no status file records this week as failed: week '$week', state '$state'"
fi

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
