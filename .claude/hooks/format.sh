#!/usr/bin/env bash
# PostToolUse hook (Write|Edit): format the one file the tool just wrote, with
# the same formatters pre-commit runs at commit time, so a long line or a
# reflow never costs a round trip. Formatting only; never blocks, never fails
# the tool call. Runs from the repo root (pre-commit needs it).
set -u
root=${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}
cd "$root" || exit 0
f=$(jq -r '.tool_input.file_path // .tool_response.filePath // empty')
[ -n "$f" ] && [ -f "$f" ] || exit 0
case "$f" in
  *.py) .venv/bin/ruff format --quiet "$f" ;;
  "$root"/apps/web/*.ts|"$root"/apps/web/*.tsx|"$root"/apps/web/*.css|"$root"/apps/web/*.json|"$root"/apps/web/*.md)
    case "$f" in *node_modules*|*/.next/*|*/lib/openapi.ts) exit 0 ;; esac
    .venv/bin/pre-commit run prettier --files "$f" > /dev/null ;;
esac
exit 0
