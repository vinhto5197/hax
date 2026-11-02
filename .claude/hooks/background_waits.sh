#!/usr/bin/env bash
# PreToolUse hook on Bash: a command that waits on something outside this
# session (CI checks, a GitHub run, the journey suite) must run with
# run_in_background, which re-invokes the session when it ends. In the
# foreground it would hold every other answer in the maintainer's message until
# it finished (Vinh, 2026-11-02: "nothing waits that doesn't have to";
# backlog 107 (e)). A one-shot look (`gh pr checks 72`, `gh run view`) passes.
# Any failure: silent, exit 0.
set -u
input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // empty' 2>/dev/null) || exit 0
[ -n "$cmd" ] || exit 0
[ "$(echo "$input" | jq -r '.tool_input.run_in_background // false' 2>/dev/null)" = true ] && exit 0

# Only where a command starts (line start, after ; & | ( or do/then, past an
# optional `direnv exec <dir>`): a commit message or echo that merely names
# one of these commands passes.
start='(^|[;&|(]|\bdo\b|\bthen\b)[[:space:]]*(direnv exec [^[:space:]]+[[:space:]]+)?'
printf '%s\n' "$cmd" | grep -Eq "${start}(gh pr checks[^|;&]*--watch|gh run watch|make e2e|until\b[^;]*gh (pr checks|run))" || exit 0

jq -n '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny",
  permissionDecisionReason: "This command waits on CI, a run or the journey suite. Rerun it with run_in_background: true, then answer everything else in the maintainer'"'"'s message now; the background task re-invokes you when it ends (backlog 107 (e))."}}'
exit 0
