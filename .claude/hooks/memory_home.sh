#!/usr/bin/env bash
# PostToolUse hook on Write|Edit: after a write to an auto-memory file
# (~/.claude/projects/<project>/memory/*.md, not the MEMORY.md index), return
# the one-home rule as additional context, so a memory that restates a rule
# living in a skill, CLAUDE.md or the Makefile is caught as it is written
# rather than at the Friday retro. A body over 10 non-empty lines is flagged
# with its count: a memory holds the why and a pointer, which is short.
# Any other file, or any failure: silent, exit 0.
set -u
input=$(cat)
path=$(echo "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
case "$path" in */.claude/projects/*/memory/*.md) ;; *) exit 0 ;; esac
[ "$(basename "$path")" = MEMORY.md ] && exit 0
[ -f "$path" ] || exit 0

# Body = everything after the closing frontmatter fence.
lines=$(awk 'f>=2 && NF {n++} /^---$/ {f++} END {print n+0}' "$path")
note="[one home] You wrote memory $(basename "$path"). A memory holds only how Vinh wants to be worked with: the why and a pointer to the rule's one home. If the rule's format or steps live in a skill, CLAUDE.md or the Makefile, this memory must not restate them; local/rules-inventory.md lists each rule's home, and a new rule gets its line there."
[ "$lines" -gt 10 ] && note="$note This body has $lines lines: check it is not restating a rule."
jq -n --arg c "$note" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $c}}'
exit 0
