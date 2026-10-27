#!/usr/bin/env bash
# Proves .claude/hooks/due.sh: silent without a marker or when nothing is due;
# names the digest when the marker's last_digest_date is not today; names the
# retro from Friday on with the week file's tally, flagging a category seen
# twice; `mark` records each; "BAU" with nothing due gets a one-line answer.
# gh is stubbed, the clock is pinned with DUE_TODAY. Run by hand:
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

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
