#!/usr/bin/env bash
# Proves `make infra-up` starts the dev compose file with --remove-orphans, so
# a container left by a service no longer in compose.dev.yml goes on the next
# start, and that `make infra-down` never deletes volumes. Dry runs only
# (make -n): no container starts. Run by hand:
#   bash tests/scripts/test_infra_up.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
fails=0

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

# Every dry run starts from a clean make environment: a parent make's flags
# and overrides would otherwise reach this one through MAKEFLAGS.
clean_make() {
  env -u MAKEFLAGS -u MFLAGS -u MAKELEVEL -u MAKEOVERRIDES -u GNUMAKEFLAGS make "$@"
}
dry() { clean_make -s -n -C "$root" "$@" 2>&1; }

# has_word LINE WORD: WORD appears in LINE as a whole whitespace-separated token.
has_word() { printf '%s\n' "$1" | tr -s '[:space:]' '\n' | grep -qx -- "$2"; }

# ── infra-up's compose `up -d` line ──────────────────
up_ok=1
up_out=$(dry infra-up) || up_ok=0
up_line=""
if [ "$up_ok" = 1 ]; then
  while IFS= read -r line; do
    case "$line" in *compose*) ;; *) continue ;; esac
    if has_word "$line" up && has_word "$line" -d; then
      up_line=$line
      break
    fi
  done <<< "$up_out"
fi

if [ "$up_ok" = 0 ]; then
  report FAIL "make -n infra-up failed: $(echo "$up_out" | tail -n 3)"
  report FAIL "infra-up targets compose.dev.yml (no dry run)"
elif [ -z "$up_line" ]; then
  report FAIL "make -n infra-up has no compose 'up -d' line: $(echo "$up_out" | tr '\n' '|')"
  report FAIL "infra-up targets compose.dev.yml (no up line)"
else
  if has_word "$up_line" --remove-orphans; then
    report PASS "infra-up's compose up -d passes --remove-orphans"
  else
    report FAIL "infra-up's compose up -d has no --remove-orphans: $up_line"
  fi
  case "$up_line" in
    *compose.prod.yml*) report FAIL "infra-up's up line names the prod compose file: $up_line" ;;
    *"infra/compose/compose.dev.yml"*) report PASS "infra-up's up line targets infra/compose/compose.dev.yml" ;;
    *) report FAIL "infra-up's up line does not name infra/compose/compose.dev.yml: $up_line" ;;
  esac
fi

# ── infra-down keeps the volumes ────────────────────────
if down_out=$(dry infra-down); then
  down_line=""
  while IFS= read -r line; do
    case "$line" in *compose*) ;; *) continue ;; esac
    if has_word "$line" down; then
      down_line=$line
      break
    fi
  done <<< "$down_out"
  if [ -z "$down_line" ]; then
    report FAIL "make -n infra-down has no compose 'down' line: $(echo "$down_out" | tr '\n' '|')"
  elif has_word "$down_line" -v || has_word "$down_line" --volumes; then
    report FAIL "infra-down deletes volumes: $down_line"
  else
    report PASS "infra-down's compose down passes no -v or --volumes"
  fi
else
  report FAIL "make -n infra-down failed: $(echo "$down_out" | tail -n 3)"
fi

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
