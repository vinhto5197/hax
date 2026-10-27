#!/usr/bin/env bash
# Proves .claude/hooks/due.sh: silent without a marker or when nothing is due;
# names the digest when the marker's last_digest_date is not today; names the
# retro from Friday on with the week file's tally, flagging a category seen
# twice; `mark` records each; "BAU" with nothing due gets a one-line answer;
# from Friday it launches the week's explorer once, waits with the reason when
# the runner's check fails, and reports the run's end until it is marked.
# gh and scripts/explorer.sh are stubbed, the clock is pinned with DUE_TODAY.
# Run by hand:
#   bash tests/scripts/test_due_hook.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
hook=$root/.claude/hooks/due.sh
work=$(mktemp -d "${TMPDIR:-/tmp}/due-hook-test.XXXXXX")
fails=0
trap 'rm -rf "$work"' EXIT

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

mkdir -p "$work/bin" "$work/proj"
printf '#!/bin/sh\necho "3 routine, 1 journey, 0 feature"\n' > "$work/bin/gh"
chmod +x "$work/bin/gh"
marker=$work/proj/local/routine-marker.json

run() { # $1 = DUE_TODAY, $2 = prompt
  printf '{"prompt": "%s"}' "$2" \
    | PATH="$work/bin:$PATH" CLAUDE_PROJECT_DIR="$work/proj" DUE_TODAY="$1" "$hook"
}

# (a) No local/ at all: a fresh clone runs no lanes, so nothing is said.
out=$(run 2026-10-27 hello)
[ -z "$out" ] && report PASS "fresh clone: silent" || report FAIL "fresh clone: got '$out'"

# (a2) local/ present but the marker gone: a configured machine that lost its
# state is named, never mistaken for "nothing due".
mkdir -p "$work/proj/local/retro"
out=$(run 2026-10-27 hello)
case "$out" in *"MARKER MISSING"*) report PASS "lost marker is named" ;; *) report FAIL "lost marker: got '$out'" ;; esac

# (b) Last digest yesterday, a Tuesday: the digest is due, with the PR counts.
echo '{"last_digest_date": "2026-10-26"}' > "$marker"
out=$(run 2026-10-27 hello)
case "$out" in
  *"DIGEST DUE"*"3 routine, 1 journey"*) report PASS "digest due names the open PRs" ;;
  *) report FAIL "digest due: got '$out'" ;;
esac
case "$out" in *"RETRO DUE"*) report FAIL "retro named on a Tuesday" ;; *) report PASS "no retro on a Tuesday" ;; esac

# (c) mark digest records today; the same day is then silent.
CLAUDE_PROJECT_DIR="$work/proj" DUE_TODAY=2026-10-27 "$hook" mark digest
got=$(jq -r .last_digest_date "$marker")
[ "$got" = 2026-10-27 ] && report PASS "mark digest records the date" || report FAIL "mark digest: got '$got'"
out=$(run 2026-10-27 hello)
[ -z "$out" ] && report PASS "digest done today: silent" || report FAIL "digest done: got '$out'"

# (d) BAU with nothing due answers in one line.
out=$(run 2026-10-27 BAU)
case "$out" in *"nothing is due"*) report PASS "BAU with nothing due" ;; *) report FAIL "BAU: got '$out'" ;; esac

# (e) Friday 2026-10-30 (W44), digest already done that day: the retro is due,
# with the tally; a category seen twice is flagged recurring.
jq '.last_digest_date = "2026-10-30"' "$marker" > "$marker.tmp" && mv "$marker.tmp" "$marker"
cat > "$work/proj/local/retro/2026-W44.md" <<'EOF'
- 2026-10-27 [forgot] journeys run unread
- 2026-10-28 [forgot] digest skipped
- 2026-10-29 [tool-quirk] connectors re-attached
EOF
out=$(run 2026-10-30 hello)
case "$out" in
  *"RETRO DUE for 2026-W44"*"forgot 2 (recurring)"*"tool-quirk 1"*) report PASS "Friday names the retro with the tally" ;;
  *) report FAIL "Friday retro: got '$out'" ;;
esac
case "$out" in *"DIGEST DUE"*) report FAIL "digest named after it was done" ;; *) report PASS "only the retro on Friday after the digest" ;; esac

# (f) mark retro records the ISO week; Saturday of the same week is silent.
CLAUDE_PROJECT_DIR="$work/proj" DUE_TODAY=2026-10-30 "$hook" mark retro
jq '.last_digest_date = "2026-10-31"' "$marker" > "$marker.tmp" && mv "$marker.tmp" "$marker"
out=$(run 2026-10-31 hello)
[ -z "$out" ] && report PASS "retro done this week: silent" || report FAIL "after mark retro: got '$out'"

# The explorer. The stub runner answers --check from files and records each
# launch; the hook starts it in the background, so a launch is polled for.
mkdir -p "$work/proj/scripts" "$work/proj/local/explorer"
cat > "$work/proj/scripts/explorer.sh" <<STUB
#!/bin/sh
if [ "\$1" = --check ]; then cat "$work/check"; exit "\$(cat "$work/check-exit")"; fi
echo "\$DUE_TODAY" >> "$work/launched"
STUB
chmod +x "$work/proj/scripts/explorer.sh"
launches() { if [ -f "$work/launched" ]; then wc -l < "$work/launched" | tr -d ' '; else echo 0; fi; }
wait_launch() { for _ in $(seq 20); do [ "$(launches)" -ge "$1" ] && return; sleep 0.1; done; }
set_marker() { jq "$1" "$marker" > "$marker.tmp" && mv "$marker.tmp" "$marker"; }
explorer_status() { echo "$1" > "$work/proj/local/explorer/.status.json"; }

# (g) Thursday 2026-11-05: no explorer before Friday.
set_marker '.last_digest_date = "2026-11-05"'
printf 'ok busy' > "$work/check"; echo 0 > "$work/check-exit"
out=$(run 2026-11-05 hello)
[ -z "$out" ] && [ "$(launches)" = 0 ] && report PASS "no explorer before Friday" || report FAIL "Thursday: got '$out', launches $(launches)"

# (h) Friday 2026-11-06 (W45) with the infra down: the reason, no launch, and
# the week stays open so the next prompt tries again.
set_marker '.last_digest_date = "2026-11-06" | .last_retro_week = "2026-W45"'
printf 'Postgres :5432 is unreachable: start Docker and run make infra-up' > "$work/check"; echo 1 > "$work/check-exit"
out=$(run 2026-11-06 BAU)
case "$out" in *"EXPLORER WAITING for 2026-W45: Postgres :5432 is unreachable"*) report PASS "a failed check names its reason" ;; *) report FAIL "waiting: got '$out'" ;; esac
[ "$(launches)" = 0 ] && [ "$(jq -r '.last_explorer_week // ""' "$marker")" = "" ] \
  && report PASS "a failed check launches nothing" || report FAIL "failed check: launches $(launches), marker '$(jq -r .last_explorer_week "$marker")'"

# (i) The check passes: launched once, in the background, with the persona.
printf 'ok busy' > "$work/check"; echo 0 > "$work/check-exit"
out=$(run 2026-11-06 BAU)
wait_launch 1
case "$out" in *"EXPLORER LAUNCHED for 2026-W45: persona busy"*) report PASS "Friday launches the explorer" ;; *) report FAIL "launch: got '$out'" ;; esac
[ "$(launches)" = 1 ] && [ "$(jq -r .last_explorer_week "$marker")" = 2026-W45 ] \
  && report PASS "the launch is recorded for the week" || report FAIL "launches $(launches), marker '$(jq -r .last_explorer_week "$marker")'"

# (j) Later prompts that week never launch again; while it runs, nothing is said.
explorer_status '{"week": "2026-W45", "state": "running"}'
run 2026-11-06 hello >/dev/null
set_marker '.last_digest_date = "2026-11-07"'
out=$(run 2026-11-07 hello)
sleep 0.5
[ -z "$out" ] && [ "$(launches)" = 1 ] && report PASS "one launch a week, silent while it runs" || report FAIL "relaunch: got '$out', launches $(launches)"

# (k) A failed run names its reason and its logs.
explorer_status '{"week": "2026-W45", "state": "failed", "reason": "the API did not answer in 60s", "logs": "local/explorer/2026-11-06-busy/"}'
out=$(run 2026-11-07 hello)
case "$out" in *"EXPLORER FAILED for 2026-W45: the API did not answer in 60s. Logs: local/explorer/2026-11-06-busy/"*) report PASS "a failed run names its reason and logs" ;; *) report FAIL "failed run: got '$out'" ;; esac

# (l) A finished run is reported until it is marked.
explorer_status '{"week": "2026-W45", "state": "done", "persona": "busy", "notes": "local/explorer/2026-11-06-busy.md"}'
out=$(run 2026-11-07 hello)
case "$out" in *"EXPLORER DONE for 2026-W45: persona busy, notes local/explorer/2026-11-06-busy.md"*) report PASS "a finished run is reported" ;; *) report FAIL "done: got '$out'" ;; esac
CLAUDE_PROJECT_DIR="$work/proj" DUE_TODAY=2026-11-07 "$hook" mark explorer
out=$(run 2026-11-07 hello)
[ -z "$out" ] && report PASS "mark explorer silences it" || report FAIL "after mark explorer: got '$out'"

# (l2) Next week, launched but not yet written its status: last week's
# finished run is not reported as this week's.
set_marker '.last_digest_date = "2026-11-13" | .last_retro_week = "2026-W46" | .last_explorer_week = "2026-W46"'
out=$(run 2026-11-13 hello)
[ -z "$out" ] && report PASS "last week's run is not this week's" || report FAIL "stale status: got '$out'"

# (m) The explorer's own session: no reminders, never a second explorer.
set_marker '.last_digest_date = "2026-11-12" | del(.last_explorer_week)'
out=$(printf '{"prompt": "go"}' | PATH="$work/bin:$PATH" CLAUDE_PROJECT_DIR="$work/proj" DUE_TODAY=2026-11-13 HAX_EXPLORER_RUN=1 "$hook")
sleep 0.5
[ -z "$out" ] && [ "$(launches)" = 1 ] && report PASS "the explorer's own session is silent" || report FAIL "inside the explorer: got '$out', launches $(launches)"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
