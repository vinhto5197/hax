#!/usr/bin/env bash
# Fails when a change ADDS a line containing the maintainer's personal
# details (name, email: whole words, any case). The repository is public; the
# denylist itself is never committed: it comes from PERSONAL_DENYLIST (a CI
# secret, one string per line) or the gitignored local/personal-denylist.txt.
# Only file:line is printed, never the string or the line, because CI logs
# are public. With no denylist the check says so and passes.
#
#   scripts/check_personal.sh --staged          what is about to be committed (pre-commit)
#   scripts/check_personal.sh --range A..B      what a push or PR adds (CI)
set -u
root=$(git rev-parse --show-toplevel)
list=$(mktemp)
trap 'rm -f "$list"' EXIT
if [ -n "${PERSONAL_DENYLIST:-}" ]; then
  printf '%s\n' "$PERSONAL_DENYLIST" | grep -v '^[[:space:]]*$' > "$list"
elif [ -f "$root/local/personal-denylist.txt" ]; then
  grep -v '^[[:space:]]*$' "$root/local/personal-denylist.txt" > "$list"
fi
if [ ! -s "$list" ]; then
  echo "personal-info check skipped: no denylist (PERSONAL_DENYLIST or local/personal-denylist.txt)"
  exit 0
fi

case "${1:-}" in
  --staged) diff_args=(--cached) ;;
  --range) diff_args=("${2:?usage: --range A..B}") ;;
  *) echo "usage: check_personal.sh --staged | --range A..B" >&2; exit 64 ;;
esac

# Walk the unified diff: track the file and the new-side line number, and test
# only added lines.
hits=$(git diff --unified=0 --no-color "${diff_args[@]}" | awk '
  /^\+\+\+ / { file = substr($0, 7); next }
  /^@@ / { split($3, a, ","); line = substr(a[1], 2) + 0; next }
  /^\+/ { print file ":" line "\t" substr($0, 2); line++; next }
' | while IFS=$'\t' read -r where text; do
  printf '%s\n' "$text" | grep -qiwF -f "$list" && echo "$where"
done)

if [ -n "$hits" ]; then
  echo "personal-info check: these added lines carry the maintainer's personal details; use \"the maintainer\" instead:"
  printf '  %s\n' $hits
  exit 1
fi
exit 0
