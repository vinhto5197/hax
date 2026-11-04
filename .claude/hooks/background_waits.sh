#!/usr/bin/env bash
# PreToolUse hook on Bash: a command that waits on something outside this
# session (CI checks, a GitHub run, the journey suite) must run with
# run_in_background, which re-invokes the session when it ends. In the
# foreground it would hold every other answer in the maintainer's message until
# it finished ("nothing waits that doesn't have to"). A one-shot look
# (`gh pr checks 72`, `gh run view`) passes; the same look polled in a
# while/until/for loop is a wait.
# Any failure: silent, exit 0.
set -u
input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // empty' 2>/dev/null) || exit 0
[ -n "$cmd" ] || exit 0
[ "$(echo "$input" | jq -r '.tool_input.run_in_background // false' 2>/dev/null)" = true ] && exit 0

# Heredoc bodies and quoted strings are text, not commands: a commit message,
# an echo or a file written by `cat <<EOF` that merely names a wait passes.
# Heredocs go first, so a quoted delimiter is still recognised. Newlines become
# `;` so a loop written over several lines is matched as one.
code=$(printf '%s\n' "$cmd" | perl -0777 -pe '
  s/(?<!<)<<(?!<)-?[ \t]*([\x27"]?)(\w+)\1([^\n]*\n).*?^\t*\2[ \t]*$/$3/gms;
  s/\x27[^\x27]*\x27//g;
  s/"(?:[^"\\]|\\.)*"//gs;
  s/\n/;/g;
' 2>/dev/null) || exit 0

# A wait is one of these where a command starts (line start, after ; & | ( or
# do/then, past optional `direnv exec <dir>`, `time` and env assignments), or
# a loop that polls: its own body (up to its first `done`) looks at a PR or a
# run AND sleeps or watches. A loop that looks once at several PRs or runs,
# `npx playwright test --list`, and a loop next to an unrelated look pass.
printf '%s\n' "$code" | perl -ne '
  my $start = qr/(?:^|[;&|(]|\bdo\b|\bthen\b)\s*(?:(?:direnv exec \S+|time|[A-Za-z_]\w*=\S*)\s+)*/;
  my $look = qr/gh (?:pr checks|run (?:view|watch))/;
  $wait = 1 if /$start(?:gh pr checks[^|;&]*--watch|gh run watch|make\s+(?:-C\s*\S+\s+)?e2e(?![-\w])|npx playwright test(?![^;&|]*--list)|until\b[^;]*$look)/;
  while (/\b(?:while|until|for)\b((?:(?!\bdone\b).)*)\bdone\b/g) {
    my $body = $1;
    $wait = 1 if $body =~ $look && $body =~ /\bsleep\b|--watch/;
  }
  END { exit($wait ? 0 : 1) }
' || exit 0

jq -n '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny",
  permissionDecisionReason: "This command waits on CI, a run or the journey suite. Rerun it with run_in_background: true, then answer everything else in the maintainer'"'"'s message now; the background task re-invokes you when it ends."}}'
exit 0
