#!/usr/bin/env bash
# Proves the secret env files (.env, infra/compose/.env.local,
# infra/compose/.env.prod) are kept from agents on both paths: Read(...)
# deny rules in .claude/settings.json, and .claude/hooks/env_guard.sh, a
# PreToolUse hook on Bash that refuses (exit 2, reason on stderr) a command
# naming one of them. The committed templates (.env.example,
# infra/compose/.env.prod.example) and .envrc stay readable, and `direnv exec`
# (which loads .env without printing it) is not refused.
# Rule matching is deliberately simple: a Read(...) pattern has a leading
# "/" (project root) or "./" dropped and is compared as a bash glob (where * also crosses "/"),
# both as written and with a leading "**/" removed, so "**/.env" covers the
# root file too. The secret files are denied in project-root form
# (Read(/.env)), never cwd-relative (Read(./.env)): a "./" rule does not
# protect a session whose cwd is a subdirectory. Run by hand:
#   bash tests/scripts/test_env_deny.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
settings=$root/.claude/settings.json
hook=$root/.claude/hooks/env_guard.sh
work=$(mktemp -d "${TMPDIR:-/tmp}/env-deny-test.XXXXXX")
. "$root/tests/scripts/lib.sh"
trap 'rm -rf "$work"' EXIT

# --- a. Read deny rules -----------------------------------------------------
if jq -e '.permissions.deny | type == "array"' "$settings" > /dev/null 2>&1; then
  report PASS "settings.json has a permissions.deny array"
else
  report FAIL "settings.json has no permissions.deny array"
fi
jq -r '.permissions.deny // [] | .[]' "$settings" > "$work/deny.txt" 2>/dev/null || : > "$work/deny.txt"
sed -nE 's/^Read\((.*)\)$/\1/p' "$work/deny.txt" > "$work/read_raw.txt"
sed -E 's|^\.?/||' "$work/read_raw.txt" > "$work/read.txt"

denied_by_read() { # $1 = repo-relative path
  local pat
  while IFS= read -r pat; do
    # shellcheck disable=SC2053
    [[ $1 == $pat ]] && return 0
    [[ $pat == '**/'* ]] && [[ $1 == ${pat#\*\*/} ]] && return 0
  done < "$work/read.txt"
  return 1
}

for f in .env infra/compose/.env.local infra/compose/.env.prod; do
  denied_by_read "$f" && report PASS "a Read deny rule covers $f" || report FAIL "no Read deny rule covers $f"
done

for f in .env infra/compose/.env.local infra/compose/.env.prod; do
  if grep -qxF "./$f" "$work/read_raw.txt"; then
    report FAIL "$f is denied in cwd-relative form: Read(./$f)"
  else
    report PASS "$f is not denied in cwd-relative ./ form"
  fi
done

examples=$(grep -F '.example' "$work/deny.txt" || true)
[ -z "$examples" ] && report PASS "no deny rule names an .example file" \
  || report FAIL "a deny rule names an .example file: $examples"
for f in .env.example infra/compose/.env.prod.example; do
  denied_by_read "$f" && report FAIL "a Read deny rule also matches $f" || report PASS "$f stays readable"
done

# --- b. The Bash hook -------------------------------------------------------
if jq -e '[.hooks.PreToolUse // [] | .[]
    | select((.matcher // "") | split("|") | index("Bash"))
    | .hooks[]?.command // "" | select(test("\\.claude/hooks/env_guard\\.sh"))] | length > 0' \
    "$settings" > /dev/null 2>&1; then
  report PASS "env_guard.sh is registered as a PreToolUse hook on Bash"
else
  report FAIL "env_guard.sh is not registered as a PreToolUse hook with matcher Bash"
fi
[ -x "$hook" ] && report PASS "env_guard.sh exists and is executable" || report FAIL "no executable $hook"

run() { # $1 = command; sets rc and err. The command goes through a file,
  # not argv, so a very long one fits.
  rc=0
  printf '%s' "$1" > "$work/cmd"
  jq -cn --rawfile c "$work/cmd" '{hook_event_name:"PreToolUse", tool_name:"Bash", tool_input:{command:$c}}' \
    | "$hook" > /dev/null 2> "$work/err" || rc=$?
  err=$(head -c 300 "$work/err")
}

for cmd in 'cat .env' 'grep X infra/compose/.env.prod' 'head infra/compose/.env.local' \
  'cp .env /tmp/x' 'less ./.env' 'printenv' 'printenv ANTHROPIC_API_KEY' 'direnv exec . env' \
  'direnv exec . printenv ANTHROPIC_API_KEY'; do
  run "$cmd"
  if [ "$rc" -eq 2 ] && [ -n "$err" ]; then
    report PASS "refused (exit 2, reason on stderr): $cmd"
  else
    report FAIL "not refused: $cmd (exit $rc, stderr '${err}')"
  fi
done

for cmd in 'direnv exec . make test' 'cat .env.example' 'cat infra/compose/.env.prod.example' \
  'cat .env.prod.example' 'ls -a' 'git status' 'grep -c foo README.md' 'cat .envrc' \
  'git commit -m "fix: keep .env from agents"' 'gh pr create --body "never reads .env"' \
  "grep -rn -F '.env' docs" 'env -i PATH=/usr/bin python3 -c 1'; do
  run "$cmd"
  [ "$rc" -eq 0 ] && report PASS "allowed (exit 0): $cmd" || report FAIL "not allowed: $cmd (exit $rc, stderr '${err}')"
done

# An early match in a very long command is still refused: the hook must not
# give up (or allow) on size.
long="cat .env # $(printf '%300000s' '' | tr ' ' x)"
[ "${#long}" -gt 300000 ] || { report FAIL "the long command was not built (${#long} bytes)"; }
run "$long"
if [ "$rc" -eq 2 ] && [ -n "$err" ]; then
  report PASS "refused (exit 2, reason on stderr): a ~300 KB command starting 'cat .env'"
else
  report FAIL "not refused: a ~300 KB command starting 'cat .env' (exit $rc, stderr '${err}')"
fi

finish
