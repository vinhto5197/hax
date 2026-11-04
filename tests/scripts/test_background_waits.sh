#!/usr/bin/env bash
# Proves .claude/hooks/background_waits.sh (a PreToolUse hook on Bash): a
# command that waits on CI, a deploy or the journey suite is refused when it
# would run in the foreground, and allowed with run_in_background; other
# commands, and a second look at a finished run, pass. Run by hand:
#   bash tests/scripts/test_background_waits.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
hook=$root/.claude/hooks/background_waits.sh
fails=0

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}
run() { # $1 = command, $2 = run_in_background (true|false)
  jq -cn --arg c "$1" --argjson b "$2" \
    '{hook_event_name:"PreToolUse", tool_name:"Bash", tool_input:{command:$c, run_in_background:$b}}' | "$hook"
}
denied() { [ "$(echo "$1" | jq -r '.hookSpecificOutput.permissionDecision // empty' 2>/dev/null)" = deny ]; }

for cmd in 'gh pr checks 72 --watch --interval 30' 'gh run watch 123' 'make e2e ARGS="e2e/stop.member.spec.ts"' \
  'direnv exec . make e2e' 'until ! gh pr checks 28 | grep -q pending; do sleep 30; done'; do
  out=$(run "$cmd" false)
  denied "$out" && report PASS "foreground wait refused: $cmd" || report FAIL "foreground wait allowed: $cmd: '$out'"
  out=$(run "$cmd" true)
  [ -z "$out" ] && report PASS "background wait allowed: $cmd" || report FAIL "background wait refused: $cmd: '$out'"
done

out=$(run 'gh pr checks 72' false)
[ -z "$out" ] && report PASS "a one-shot look at checks passes" || report FAIL "one-shot look refused: '$out'"

out=$(run 'gh run view 123 --json conclusion' false)
[ -z "$out" ] && report PASS "reading a finished run passes" || report FAIL "run view refused: '$out'"

out=$(run 'make test-web' false)
[ -z "$out" ] && report PASS "a unit suite passes" || report FAIL "unit suite refused: '$out'"

out=$(run 'git commit -m "the hook refuses gh run watch, gh pr checks --watch and make e2e"' false)
[ -z "$out" ] && report PASS "a command that only mentions the words passes" || report FAIL "a mention was refused: '$out'"

out=$(run $'cd /x && git fetch -q\nmake e2e' false)
denied "$out" && report PASS "a wait on a later line is refused" || report FAIL "later-line wait allowed: '$out'"

out=$(run 'git log --oneline -1' false)
[ -z "$out" ] && report PASS "an ordinary command passes" || report FAIL "ordinary command refused: '$out'"

out=$(run 'gh pr checks 72 --watch' false)
case "$out" in *run_in_background*answer*) report PASS "the reason names the fix and the why" ;; *) report FAIL "reason: '$out'" ;; esac

out=$(jq -cn '{hook_event_name:"PreToolUse", tool_name:"Bash", tool_input:{command:"gh run watch 1"}}' | "$hook")
denied "$out" && report PASS "a missing run_in_background counts as foreground" || report FAIL "missing flag allowed: '$out'"

out=$(echo '{}' | "$hook"; echo "exit=$?")
[ "$out" = "exit=0" ] && report PASS "bad input: silent, exit 0" || report FAIL "bad input: '$out'"

# Waits that poll in a loop or reach the journey suite by another spelling.
waits=(
  'while true; do gh pr checks 12; sleep 5; done'
  'while ! gh run view 7 --exit-status; do sleep 5; done'
  'for i in $(seq 1 30); do gh pr checks 12 && break; sleep 10; done'
  'time make e2e'
  'make -C apps/web e2e'
  'E2E_WORKERS=2 make e2e'
  'npx playwright test'
  'cd apps/web && npx playwright test'
  'cd x && make e2e'
)
for cmd in "${waits[@]}"; do
  out=$(run "$cmd" false)
  denied "$out" && report PASS "foreground wait refused: $cmd" || report FAIL "foreground wait allowed: $cmd: '$out'"
  out=$(run "$cmd" true)
  [ -z "$out" ] && report PASS "background wait allowed: $cmd" || report FAIL "background wait refused: $cmd: '$out'"
done

# Commands whose quoted text or heredoc body merely names a wait.
heredoc=$(cat <<'OUTER'
cat > f <<'EOF'
cd x && make e2e
EOF
OUTER
)
mentions=(
  "$heredoc"
  'echo "a; make e2e"'
  'git commit -m "make e2e; done"'
  'echo "run make e2e later"'
  'grep -n "make e2e" Makefile'
)
for cmd in "${mentions[@]}"; do
  out=$(run "$cmd" false)
  [ -z "$out" ] && report PASS "a mention is allowed: $(printf '%s' "$cmd" | head -1)" || report FAIL "a mention was refused: $cmd: '$out'"
done

# One-shot looks, in loops or not, that never wait.
oneshots=(
  'for pr in 44 45; do gh pr checks $pr; done'
  'for id in 1 2; do gh run view $id --json conclusion; done'
  "gh run list --json databaseId -q '.[].databaseId' | while read x; do gh run view \"\$x\" --log-failed | tail -5; done"
  'npx playwright test --list'
  $'for f in a b; do echo $f; done\ngh run view 12 --log | grep done'
)
for cmd in "${oneshots[@]}"; do
  out=$(run "$cmd" false)
  [ -z "$out" ] && report PASS "a one-shot command is allowed in the foreground: $(printf '%s' "$cmd" | tr '\n' ' ')" \
    || report FAIL "a one-shot command was refused: $cmd: '$out'"
done

out=$(run 'make test' false)
[ -z "$out" ] && report PASS "make test passes" || report FAIL "make test refused: '$out'"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
