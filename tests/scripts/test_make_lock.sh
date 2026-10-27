#!/usr/bin/env bash
# Proves the Makefile's gate lock: on a configured machine (local/ present),
# `make test` and `make e2e` always run under scripts/with-lock.sh, whether or
# not HAX_LOCK is set, so two runs sharing hax_test or the e2e stack queue
# instead of emptying each other's database. Without local/ (CI, a fresh
# clone) they run unlocked, since the lock directory has nowhere to live.
# Dry runs only (make -n): nothing is executed. Run by hand:
#   bash tests/scripts/test_make_lock.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/make-lock-test.XXXXXX")
fails=0
trap 'rm -rf "$work"' EXIT

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

cp "$root/Makefile" "$work/Makefile"
dry() { make -s -n -C "$work" "$@" 2>/dev/null; }

for target in test e2e; do
  mkdir -p "$work/local"
  case "$(dry "$target")" in
    *"with-lock.sh local/.gate.lock"*) report PASS "$target locks without HAX_LOCK" ;;
    *) report FAIL "$target ran unlocked on a configured machine" ;;
  esac
  rm -rf "$work/local"
  case "$(dry "$target")" in
    *"with-lock.sh"*) report FAIL "$target locked with no local/ (CI would fail)" ;;
    *) report PASS "$target runs unlocked without local/" ;;
  esac
done

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
