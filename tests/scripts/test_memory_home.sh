#!/usr/bin/env bash
# Proves .claude/hooks/memory_home.sh (a PostToolUse hook on Write|Edit): a
# write to a memory file under ~/.claude/projects/*/memory/ returns the
# one-home reminder as additional context, flagging a body long enough to be
# restating a rule; MEMORY.md (the index) and every other file get nothing.
# Run by hand:
#   bash tests/scripts/test_memory_home.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
hook=$root/.claude/hooks/memory_home.sh
work=$(mktemp -d "${TMPDIR:-/tmp}/memory-home-test.XXXXXX")
fails=0
trap 'rm -rf "$work"' EXIT

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

mem=$work/.claude/projects/-x-proj/memory
mkdir -p "$mem" "$work/repo"
run() { jq -cn --arg p "$1" '{hook_event_name:"PostToolUse", tool_name:"Write", tool_input:{file_path:$p}}' | "$hook"; }
context() { echo "$1" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null; }

printf -- '---\nname: short\n---\n\nVinh wants X.\n\n**Why:** Vinh said so.\n\nPointer: skill gate-block.\n' > "$mem/feedback_short.md"
out=$(context "$(run "$mem/feedback_short.md")")
case "$out" in *"one home"*"rules-inventory"*) report PASS "a memory write gets the one-home reminder" ;; *) report FAIL "short memory: '$out'" ;; esac
case "$out" in *"lines"*) report FAIL "a short body was flagged as long" ;; *) report PASS "a short body is not flagged" ;; esac

{ printf -- '---\nname: long\n---\n\n'; for i in $(seq 1 14); do echo "Rule line $i."; done; } > "$mem/feedback_long.md"
out=$(context "$(run "$mem/feedback_long.md")")
case "$out" in *"14 lines"*) report PASS "a long body is flagged with its line count" ;; *) report FAIL "long memory: '$out'" ;; esac

echo "- [x](x.md) — y" > "$mem/MEMORY.md"
out=$(run "$mem/MEMORY.md")
[ -z "$out" ] && report PASS "the index gets nothing" || report FAIL "MEMORY.md: '$out'"

echo "x" > "$work/repo/notes.md"
out=$(run "$work/repo/notes.md")
[ -z "$out" ] && report PASS "a file outside memory gets nothing" || report FAIL "other file: '$out'"

out=$(echo '{}' | "$hook"; echo "exit=$?")
[ "$out" = "exit=0" ] && report PASS "no input: silent, exit 0" || report FAIL "no input: '$out'"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
