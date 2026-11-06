#!/usr/bin/env bash
# PreToolUse hook on Bash: refuses a command that names a secret env file
# (.env, .env.local or .env.prod, bare or under any directory: the root .env
# and infra/compose/.env.local, .env.prod) as a path word, or that prints the
# environment direnv loaded (`printenv` as a command, `direnv exec <dir> env`
# or `export` with nothing after). The Read(...) deny rules in settings.json
# cover the Read tool. Templates (*.example), .envrc and `direnv exec <dir>
# <cmd>` pass. Quoted strings are text, not paths, and are dropped first.
# Known gaps of a guard rail: quoted paths, globs (.e*), recursive grep.
set -euo pipefail
cmd=$(jq -r '.tool_input.command // empty' 2>/dev/null) || exit 0
[ -n "$cmd" ] || exit 0
code=$(perl -0777 -pe 's/\x27[^\x27]*\x27//g; s/"(?:[^"\\]|\\.)*"//gs; s/\n/;/g' <<<"$cmd" 2>/dev/null) || exit 0

path='(^|[[:space:]=<>|;&(])([^[:space:]]*/)?\.env(\.(local|prod))?($|[[:space:]);&|<>])'
start='(^|[;&|(`]|\$\()[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+|(sudo|exec|command|time)[[:space:]]+|direnv[[:space:]]+exec[[:space:]]+[^[:space:]]+[[:space:]]+)*'
dump="${start}printenv($|[^A-Za-z0-9_.-])|direnv[[:space:]]+exec[[:space:]]+[^[:space:]]+[[:space:]]+(env|export)[[:space:]]*($|[;&|)])"
if grep -qE "$path" <<<"$code"; then
  echo "Refused: this command names a secret env file (.env, .env.local, .env.prod); use direnv exec, or ask the maintainer." >&2
  exit 2
fi
if grep -qE "$dump" <<<"$code"; then
  echo "Refused: this command prints the environment, which holds the secrets from .env; use direnv exec <dir> <cmd>, or ask the maintainer." >&2
  exit 2
fi
exit 0
