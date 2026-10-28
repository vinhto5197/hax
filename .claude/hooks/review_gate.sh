#!/usr/bin/env bash
# Stop hook: a final message that asks the maintainer for a review word
# ("merge", "commit", "approved", "push", "go <id>", in straight or curly
# quotes, after an ask cue) must carry a "Your review" section (skill gate-block, "Your review,
# on every Show and Ask"); without one the stop is refused and the reason sent
# back, so the hand-off is fixed before anyone reads it. The rule rested on
# recall and was missed; this makes it a check.
# The final message is `last_assistant_message` when the input has it, else
# the assistant text after the transcript's last user or tool-result entry. A
# second stop in a row (stop_hook_active) always passes, so the hook can never
# loop. Any failure: silent, exit 0.
set -u
input=$(cat)
[ "$(echo "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)" = true ] && exit 0

message=$(echo "$input" | jq -r '.last_assistant_message // empty' 2>/dev/null)
if [ -z "$message" ]; then
  transcript=$(echo "$input" | jq -r '.transcript_path // empty' 2>/dev/null)
  [ -n "$transcript" ] && [ -f "$transcript" ] || exit 0
  # Each user entry (a prompt or a tool result) starts the final message over.
  message=$(jq -rs '
    reduce .[] as $e (""; if $e.type == "user" then ""
      elif $e.type == "assistant" then . + ([$e.message.content[]? | select(.type == "text") | .text] | join("\n")) + "\n"
      else . end)' "$transcript" 2>/dev/null) || exit 0
fi

# An ask, not a mention: the quoted word follows an ask cue within a few
# characters ("Reply "merge"", "waits for your "commit"", "To end the review:
# "commit""). A word only quoted as an example, or an earlier ask recounted
# ("asked for your "commit""), does not fire.
asks=$(printf '%s' "$message" | grep -Eio '\b(say|reply|respond|waits? for|waiting on|end(s)? the review)\b[^"\n]{0,24}["“](merge|commit|approved|push|go [a-z0-9][a-z0-9._-]*)["”]' \
  | grep -Eio '["“](merge|commit|approved|push|go [a-z0-9][a-z0-9._-]*)["”]' | head -1)
[ -n "$asks" ] || exit 0
printf '%s' "$message" | grep -q 'Your review' && exit 0

jq -n --arg w "$asks" '{decision: "block", reason: ("Your last message asks the maintainer for " + $w + " but has no **Your review** section (skill gate-block). It is already on their screen: add only the missing section now, and do not repeat anything already said. The section: one line on what is already proven; what to look at; the judgment calls to accept or refuse; code worth raising or \"no code to read\"; the word that ends the review.")}'
exit 0
