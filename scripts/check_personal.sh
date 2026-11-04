#!/usr/bin/env bash
# Fails when a change carries the maintainer's personal details (name, email:
# whole words, any case) in an added line, an added/renamed/copied path or,
# for --range, a commit message. The repository is public; the denylist itself
# is never committed: it comes from PERSONAL_DENYLIST (a CI secret, one string
# per line) or the gitignored local/personal-denylist.txt. Only locations are
# printed (file:line, the path itself for a path hit, the short sha for a
# message hit), never a matched line or message, because CI logs are public.
#
#   scripts/check_personal.sh --staged          what is about to be committed (pre-commit)
#   scripts/check_personal.sh --range A..B      what a push or PR adds (CI)
#
# Exit 0 clean (or no denylist: says "skipped"), 1 on a hit, 2 when git cannot
# read the change, 64 on bad usage. A git failure must never read as clean.
set -u
# Bytes, not characters: a non-UTF-8 byte in an added line must neither stop
# awk (BSD: a multibyte error) nor turn grep's match into "binary file
# matches" (GNU). The denylist is ASCII words, so case folding is unchanged.
export LC_ALL=C

usage() { echo "usage: check_personal.sh --staged | --range A..B" >&2; exit 64; }
case "${1:-}" in
  --staged) diff_args=(--cached); range= ;;
  --range) [ -n "${2:-}" ] || usage; diff_args=("$2"); range=$2 ;;
  *) usage ;;
esac

die() { echo "personal-info check: git could not read the change ($1)" >&2; exit 2; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
list=$tmp/list

# Entries lose a trailing CR and trailing whitespace (a CRLF file or a
# hand-edited secret would otherwise never match); empty entries are dropped.
clean_list() { tr -d '\r' | sed 's/[[:space:]]*$//' | grep -v '^[[:space:]]*$'; }
if [ -n "${PERSONAL_DENYLIST:-}" ]; then
  printf '%s\n' "$PERSONAL_DENYLIST" | clean_list > "$list"
else
  root=$(git rev-parse --show-toplevel) || die "not a git repository"
  if [ -f "$root/local/personal-denylist.txt" ]; then
    clean_list < "$root/local/personal-denylist.txt" > "$list"
  fi
fi
if [ ! -s "$list" ]; then
  echo "personal-info check skipped: no denylist (PERSONAL_DENYLIST or local/personal-denylist.txt)"
  exit 0
fi

# User config must not change what git prints here: an external diff driver,
# textconv or a `-diff`/binary attribute would hide added lines, and
# prefix/quoting settings change paths.
gitd() {
  git -c core.quotepath=false diff --text --no-ext-diff --no-textconv --no-color \
    --src-prefix=a/ --dst-prefix=b/ "$@"
}

gitd --unified=0 "${diff_args[@]}" > "$tmp/diff" || die "git diff failed"
gitd --name-status -z -M --diff-filter=ACR "${diff_args[@]}" > "$tmp/names" \
  || die "git diff --name-status failed"

hits=$tmp/hits
: > "$hits"

# Added lines. A file's header runs from `diff --git` to its first `@@`; only
# there is `+++ ` the new path (an added line "++ x" also reads "+++ x").
# Git appends a TAB to a ---/+++ path that contains a space.
awk -v where="$tmp/where" -v text="$tmp/text" '
  /^diff --git / { hdr = 1; next }
  hdr && /^\+\+\+ / { file = substr($0, 7); sub(/\t$/, "", file); next }
  /^@@ / { hdr = 0; split($3, a, ","); line = substr(a[1], 2) + 0; next }
  hdr { next }
  /^\+/ { print file ":" line > where; print substr($0, 2) > text; line++; next }
' "$tmp/diff" || die "could not parse the diff"
if [ -s "$tmp/text" ]; then
  grep -niwF -f "$list" "$tmp/text" | cut -d: -f1 > "$tmp/nums"
  [ "${PIPESTATUS[0]}" -le 1 ] || die "grep failed"
  awk 'NR == FNR { want[$1] = 1; next } FNR in want' "$tmp/nums" "$tmp/where" >> "$hits"
fi

# Added, renamed or copied paths: -z records are STATUS, then one path (A) or
# the old and new paths (R, C); only the new path is checked.
while IFS= read -r -d '' status; do
  IFS= read -r -d '' path || break
  case "$status" in R* | C*) IFS= read -r -d '' path || break ;; esac
  printf '%s\n' "$path" | grep -qiwF -f "$list" && printf '%s (path)\n' "$path" >> "$hits"
done < "$tmp/names"

if [ -n "$range" ]; then
  commits=$(git rev-list "$range") || die "git rev-list failed"
  for c in $commits; do
    msg=$(git log -1 --format=%B "$c") || die "git log failed"
    if printf '%s\n' "$msg" | grep -qiwF -f "$list"; then
      short=$(git rev-parse --short "$c") || die "git rev-parse failed"
      printf 'commit %s (message)\n' "$short" >> "$hits"
    fi
  done
fi

if [ -s "$hits" ]; then
  echo "personal-info check: these carry the maintainer's personal details; use \"the maintainer\" instead:"
  while IFS= read -r hit; do printf '  %s\n' "$hit"; done < "$hits"
  exit 1
fi
exit 0
