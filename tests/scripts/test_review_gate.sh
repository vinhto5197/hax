#!/usr/bin/env bash
# Proves .claude/hooks/review_gate.sh (a Stop hook): a final message that asks
# the maintainer for a review word ("merge", "commit", "approved", "push",
# "go <id>") without a "Your review" section is sent back; the same message
# with the section, a message asking for nothing, and a second stop in a row
# all pass. The final message is read from the transcript (the text after the
# last user or tool-result entry), or from last_assistant_message when given.
# Run by hand:
#   bash tests/scripts/test_review_gate.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
hook=$root/.claude/hooks/review_gate.sh
work=$(mktemp -d "${TMPDIR:-/tmp}/review-gate-test.XXXXXX")
fails=0
trap 'rm -rf "$work"' EXIT

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

# A transcript whose last turn is: a human prompt, a tool call, a tool result,
# then the final message's text in two blocks.
transcript() { # $1 = final text
  local t=$work/t.jsonl
  {
    jq -cn '{type:"user", origin:{kind:"human"}, message:{role:"user", content:[{type:"text", text:"go"}]}}'
    jq -cn '{type:"assistant", message:{role:"assistant", content:[{type:"text", text:"Checking. Say \"commit\" later."}, {type:"tool_use", id:"x", name:"Bash", input:{}}]}}'
    jq -cn '{type:"user", message:{role:"user", content:[{type:"tool_result", tool_use_id:"x", content:"ok"}]}}'
    jq -cn --arg t "$1" '{type:"assistant", message:{role:"assistant", content:[{type:"text", text:$t}]}}'
    jq -cn '{type:"assistant", message:{role:"assistant", content:[{type:"text", text:"Done."}]}}'
  } > "$t"
  echo "$t"
}
run() { # $1 = transcript path, $2 = stop_hook_active
  jq -cn --arg p "$1" --argjson a "$2" '{hook_event_name:"Stop", transcript_path:$p, stop_hook_active:$a}' | "$hook"
}
blocked() { [ "$(echo "$1" | jq -r '.decision // empty' 2>/dev/null)" = block ]; }

out=$(run "$(transcript 'PR #44 is green. Reply "merge" when ready.')" false)
blocked "$out" && report PASS "an ask without Your review is sent back" || report FAIL "ask without review passed: '$out'"
case "$out" in *"Your review"*"gate-block"*) report PASS "the reason names the section and the skill" ;; *) report FAIL "reason: '$out'" ;; esac

out=$(run "$(transcript $'PR #44 is green.\n\n**Your review**\n1. Look at the screenshots.\n\nSay "merge".')" false)
[ -z "$out" ] && report PASS "an ask with Your review passes" || report FAIL "ask with review blocked: '$out'"

out=$(run "$(transcript 'The deploy is live and health answers 200.')" false)
[ -z "$out" ] && report PASS "a message asking for nothing passes" || report FAIL "plain message blocked: '$out'"

out=$(run "$(transcript 'Reply “approved” or ask for a fifth look.')" false)
blocked "$out" && report PASS "curly quotes count" || report FAIL "curly-quoted ask passed: '$out'"

out=$(run "$(transcript 'Reply "go server-turn" to start it.')" false)
blocked "$out" && report PASS "a go-word counts" || report FAIL "go-word passed: '$out'"

# An earlier message's ask (before the last tool result) is not the final one.
out=$(run "$(transcript 'All checks passed.')" false)
[ -z "$out" ] && report PASS "only the final message is judged" || report FAIL "earlier text judged: '$out'"

# A word mentioned, not asked for, passes: the check fires on an ask only.
out=$(run "$(transcript 'The check looks for a quoted review word like "merge" or "commit".')" false)
[ -z "$out" ] && report PASS "a mentioned word is not an ask" || report FAIL "a mention was blocked: '$out'"

out=$(run "$(transcript 'The skill edit waits for your "commit".')" false)
blocked "$out" && report PASS "a word waiting on the maintainer is an ask" || report FAIL "waiting-on ask passed: '$out'"

out=$(run "$(transcript $'All green.\n\n**To end the review:** "merge".')" false)
blocked "$out" && report PASS "a to-end-the-review line is an ask" || report FAIL "end-the-review ask passed: '$out'"

# Recounting an earlier ask is not an ask: "your" alone is no cue.
out=$(run "$(transcript 'My first answer asked for your "commit" without the section.')" false)
[ -z "$out" ] && report PASS "a recounted ask is not an ask" || report FAIL "recounted ask blocked: '$out'"

out=$(run "$(transcript 'Reply "merge".')" false)
case "$out" in *"only"*"do not repeat"*) report PASS "the reason asks for the section alone, no repeat" ;; *) report FAIL "reason: '$out'" ;; esac

out=$(run "$(transcript 'Reply "merge".')" true)
[ -z "$out" ] && report PASS "a second stop in a row passes" || report FAIL "stop_hook_active blocked: '$out'"

out=$(jq -cn '{hook_event_name:"Stop", stop_hook_active:false, last_assistant_message:"Say \"commit\"."}' | "$hook")
blocked "$out" && report PASS "last_assistant_message is used when given" || report FAIL "last_assistant_message: '$out'"

out=$(echo '{}' | "$hook"; echo "exit=$?")
[ "$out" = "exit=0" ] && report PASS "no transcript: silent, exit 0" || report FAIL "no transcript: '$out'"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
