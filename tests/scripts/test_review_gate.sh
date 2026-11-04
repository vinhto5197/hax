#!/usr/bin/env bash
# Proves .claude/hooks/review_gate.sh (a Stop hook): a final hand-off (it names
# a PR, a brief card's artifact link, or carries a gate block heading) that
# asks the maintainer for a review word ("merge", "commit", "approved", "push",
# "go <id>") without a "Your review" section is sent back; a plain ask with no
# hand-off passes (a sentence that only mentions a gate block, or a "#N" beside
# "PR", is no hand-off); the same message with the section, a message asking
# for nothing, and a second stop in a row all pass. The final message is read
# from the transcript (the text after the last user or tool-result entry), or
# from last_assistant_message when given.
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

out=$(run "$(transcript 'The card is at https://claude.ai/artifact/abc. Reply “approved” or ask for a fifth look.')" false)
blocked "$out" && report PASS "curly quotes count" || report FAIL "curly-quoted ask passed: '$out'"

out=$(run "$(transcript 'Card: https://claude.ai/artifact/abc. Reply "go server-turn" to start it.')" false)
blocked "$out" && report PASS "a go-word counts" || report FAIL "go-word passed: '$out'"

# An earlier message's ask (before the last tool result) is not the final one.
out=$(run "$(transcript 'All checks passed.')" false)
[ -z "$out" ] && report PASS "only the final message is judged" || report FAIL "earlier text judged: '$out'"

# A word mentioned, not asked for, passes: the check fires on an ask only.
out=$(run "$(transcript 'The check looks for a quoted review word like "merge" or "commit".')" false)
[ -z "$out" ] && report PASS "a mentioned word is not an ask" || report FAIL "a mention was blocked: '$out'"

out=$(run "$(transcript $'Gate block: slice 2\nThe slice is ready; it waits for your "merge".')" false)
blocked "$out" && report PASS "a word waiting on the maintainer is an ask" || report FAIL "waiting-on ask passed: '$out'"

# Not a hand-off: no PR, card or gate block named. A plain ask passes.
out=$(run "$(transcript 'The skill edit waits for your "commit".')" false)
[ -z "$out" ] && report PASS "a plain ask with no hand-off passes" || report FAIL "plain ask blocked: '$out'"

out=$(run "$(transcript 'CI is green. Say "merge" when ready.')" false)
[ -z "$out" ] && report PASS "a status answer with no PR named passes" || report FAIL "status answer blocked: '$out'"

out=$(run "$(transcript 'https://github.com/o/r/pull/7 is up. Reply "merge".')" false)
blocked "$out" && report PASS "a PR link is a hand-off" || report FAIL "PR link ask passed: '$out'"

out=$(run "$(transcript $'PR #44: all green.\n\n**To end the review:** "merge".')" false)
blocked "$out" && report PASS "a to-end-the-review line is an ask" || report FAIL "end-the-review ask passed: '$out'"

# Recounting an earlier ask is not an ask: "your" alone is no cue.
out=$(run "$(transcript 'My first answer asked for your "commit" without the section.')" false)
[ -z "$out" ] && report PASS "a recounted ask is not an ask" || report FAIL "recounted ask blocked: '$out'"

out=$(run "$(transcript 'PR #44: reply "merge".')" false)
case "$out" in *"only"*"do not repeat"*) report PASS "the reason asks for the section alone, no repeat" ;; *) report FAIL "reason: '$out'" ;; esac

out=$(run "$(transcript 'PR #44: reply "merge".')" true)
[ -z "$out" ] && report PASS "a second stop in a row passes" || report FAIL "stop_hook_active blocked: '$out'"

out=$(jq -cn '{hook_event_name:"Stop", stop_hook_active:false, last_assistant_message:"PR #44 is green. Say \"merge\"."}' | "$hook")
blocked "$out" && report PASS "last_assistant_message is used when given" || report FAIL "last_assistant_message: '$out'"

out=$(echo '{}' | "$hook"; echo "exit=$?")
[ "$out" = "exit=0" ] && report PASS "no transcript: silent, exit 0" || report FAIL "no transcript: '$out'"

# The final message given directly; $2 = stop_hook_active (default false).
msg() {
  jq -cn --arg m "$1" --argjson a "${2:-false}" \
    '{hook_event_name:"Stop", stop_hook_active:$a, last_assistant_message:$m}' | "$hook"
}
expect_block() { # $1 = name, $2 = message
  local out; out=$(msg "$2")
  blocked "$out" && report PASS "$1" || report FAIL "$1: '$out'"
}
expect_pass() { # $1 = name, $2 = message
  local out; out=$(msg "$2")
  [ -z "$out" ] && report PASS "$1" || report FAIL "$1: '$out'"
}

expect_block "a gap holding the letter n before the quoted word is still an ask" \
  'PR #12 is green and reviewed. It waits for the maintainer'"'"'s "merge".'
expect_block "a claude.ai/code/artifact link is a hand-off" \
  'The card is at https://claude.ai/code/artifact/3f1c2a9e-7b4d-4e2a-9c1f-0a1b2c3d4e5f. Reply "merge".'
expect_block "'Pull request #12' is a hand-off" \
  'Pull request #12 is up and green. Reply "merge".'
expect_block "'PRs #44 and #45' is a hand-off" \
  'PRs #44 and #45 are up and green. Reply "merge".'
expect_block "a two-word review word after a gate block is an ask" \
  $'**Gate block: slice 2**\nTests pass, the review found nothing.\n\nTo land it, say "commit push".'
expect_block "a gate block asking for commit without the section is sent back" \
  $'**Gate block: slice 2**\nTests pass. Say "commit" when ready.'

# A gate block is a hand-off only as a heading line; a mention in a sentence is
# a status note.
expect_pass "a status note naming the gate block above passes" \
  'F5c'"'"'s gate block above waits for "commit".'
expect_pass "a gate block mentioned mid-sentence with an ask passes" \
  'The gate block above is unchanged. Say "commit" when ready.'
expect_block "a '## Gate block' heading is a hand-off" \
  $'## Gate block\nTests pass.\n\nSay "commit" when ready.'
expect_block "a '### Gate block' heading with a suffix is a hand-off" \
  $'### Gate block — slice 3\nTests pass.\n\nSay "commit" when ready.'
expect_block "a line starting 'Gate block:' is a hand-off" \
  $'Tests pass.\nGate block: slice 3, two files.\n\nSay "commit" when ready.'
expect_block "the feature template's '# <id> — gate block' heading is a hand-off" \
  $'# F5c — gate block\nTests pass.\n\nSay "commit" when ready.'
expect_block "a heading naming a bite's gate block is a hand-off" \
  $'## Bite 2 gate block\nTests pass.\n\nSay "commit" when ready.'
expect_pass "a bold phrase opening a sentence about the gate block passes" \
  $'**F5c\'s gate block** above still waits. Say "commit" when ready.'
expect_pass "a '#N' beside 'PR' in a sentence is not a hand-off" \
  'I checked #3 in the PR list. Say "push"'

expect_block "Your review mentioned mid-sentence is not the section" \
  'PR #12 is green. I will add Your review later. Reply "merge".'
expect_block "Your review at a line start but running on into a sentence is not the section" \
  $'PR #12 is green.\nYour review is not needed on this one.\nReply "merge".'
expect_pass "a '## Your review' heading counts as the section" \
  $'PR #12 is green.\n\n## Your review\n1. Look at the sidebar.\n\nReply "merge".'
expect_pass "a bare 'Your review' line counts as the section" \
  $'PR #12 is green.\n\nYour review\n1. Look at the sidebar.\n\nReply "merge".'
expect_pass "a '**Your review**' heading counts as the section" \
  $'PR #12 is green.\n\n**Your review**\n1. Look at the sidebar.\n\nReply "merge".'

expect_pass "a '**Your review (two minutes)**' heading counts as the section" \
  $'PR #12 is green.\n\n**Your review (two minutes)**\n1. Look at the sidebar.\n\nReply "merge".'
expect_pass "a '- **Your review**' list-item heading counts as the section" \
  $'PR #12 is green.\n\n- **Your review**\n  1. Look at the sidebar.\n\nReply "merge".'
expect_pass "a '# Your review' heading counts as the section" \
  $'PR #12 is green.\n\n# Your review\n1. Look at the sidebar.\n\nReply "merge".'

out=$(msg 'PR #12 is green. Reply "merge".')
reason=$(echo "$out" | jq -r '.reason // empty' 2>/dev/null)
for part in 'Decisions for you' 'Adds to the stack' 'Calls I made'; do
  case "$reason" in *"$part"*) report PASS "the reason lists the section part '$part'" ;; *) report FAIL "reason lacks '$part': '$reason'" ;; esac
done

out=$(msg 'PR #12 is green. It waits for the maintainer'"'"'s "merge".' true)
[ -z "$out" ] && report PASS "stop_hook_active passes even a hand-off with no section" || report FAIL "stop_hook_active blocked: '$out'"
expect_pass "a plain 'say \"commit\"' with no hand-off passes" 'The edit is in. Say "commit".'
expect_pass "a word used as a noun on a PR is not an ask" \
  'PR #42 is open. The answer "merge" in the old FAQ was wrong; I fixed the doc.'
expect_pass "an earlier word recounted with 'said' is not an ask" \
  'You said "commit" earlier on PR #42, so I committed it and pushed; CI is running.'

out=$(msg 'PR #12: reply "merge".'; echo "exit=$?")
case "$out" in *"exit=0") report PASS "a block still exits 0" ;; *) report FAIL "block exit: '$out'" ;; esac

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
