#!/usr/bin/env bash
# Stop hook: a final hand-off (it names a PR or a brief card's artifact link,
# or carries a gate block heading) that asks the maintainer for a review word
# ("merge", "commit", "approved", "push", "go <id>", in straight or curly
# quotes, after an ask cue)
# must carry a "Your review" section (skill gate-block, "Your review, on every
# Ask"); without one the stop is refused and the reason sent back, so the
# hand-off is fixed before anyone reads it. A plain ask with no hand-off (a
# status answer, "say commit" for a small edit) passes: the section is for
# real hand-offs only.
# The final message is `last_assistant_message` when the input has it, else
# the assistant text after the transcript's last user or tool-result entry. A
# second stop in a row (stop_hook_active) always passes, so the hook can never
# loop. Any failure: silent, exit 0.
set -u
# The greps match curly quotes as characters, which needs a UTF-8 locale; under
# C or POSIX they are separate bytes and a curly-quoted ask is missed. Claude
# Code may start the hook in any locale. glibc lists C.UTF-8 as C.utf8.
if locale -a 2>/dev/null | grep -Eqix 'C\.utf-?8'; then export LC_ALL=C.UTF-8; else export LC_ALL=en_US.UTF-8; fi
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
# The gap excludes quotes (a quote earlier on the line must not bridge to a
# later word); grep matches per line, so it never spans a line break.
words='(merge|commit push|commit|approved|push|go [a-z0-9][a-z0-9._-]*)'
asks=$(printf '%s' "$message" | grep -Eio "\\b(say|reply|respond|waits? for|waiting on|end(s)? the review)\\b[^\"“”]{0,24}[\"“]${words}[\"”]" \
  | grep -Eio "[\"“]${words}[\"”]" | head -1)
[ -n "$asks" ] || exit 0
# A hand-off names a PR or an artifact, or carries a gate block as a heading
# line (a Markdown heading or a whole bold line that names it, as the feature
# template's "# <id> — gate block" does, or a line opening "Gate block:"); a
# gate block mentioned in a sentence (a status note) is not one.
printf '%s' "$message" | grep -Eiq '(\bPRs? #[0-9]+|\bpull requests? #[0-9]+|/pull/[0-9]+|claude\.ai/(code/)?artifact/)' \
  || printf '%s\n' "$message" | grep -Eiq '^[[:space:]]*(#+[[:space:]].*gate block|\*\*[^*]*gate block[^*]*\*\*[[:space:]]*$|Gate block:)' \
  || exit 0
# The section is a heading line, never a mention inside a sentence.
printf '%s\n' "$message" | grep -Eq '^[[:space:]]*([-*][[:space:]]+)?(\*\*Your review[^*]*\*\*|#+[[:space:]]*Your review\b|Your review[[:space:]:]*$)' && exit 0

jq -n --arg w "$asks" '{decision: "block", reason: ("Your last message asks the maintainer for " + $w + " but has no **Your review** section (skill gate-block). It is already on their screen: add only the missing section now, and do not repeat anything already said. The section: one line on what is already proven; then numbered: what to look at; **Decisions for you**; **Adds to the stack**; **Calls I made**; code worth raising or \"no code to read\"; the word that ends the review.")}'
exit 0
