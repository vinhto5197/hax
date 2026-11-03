#!/usr/bin/env bash
# Proves deploy.sh's disk gate as the box receives it: the roll script is an
# unquoted heredoc, so the gate is rendered the way deploy.sh renders it
# (local expansion, escaped \$ left for the box) and then run against a fake
# df. Under 3072 MB free the roll stops before the pull; at or above, it goes
# on. Run by hand:
#   bash tests/scripts/test_deploy_disk_gate.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/deploy-disk-test.XXXXXX")
fails=0
trap 'rm -rf "$work"' EXIT

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

# The heredoc block, from "remote=$(cat <<REMOTE" to its closing ")".
awk '/^  remote=\$\(cat <<REMOTE/{f=1} f{print} f&&/^\)$/{exit}' \
  "$root/infra/deploy/deploy.sh" > "$work/block.sh"
{
  echo 'raw=x PY_IMAGE=p WEB_IMAGE=w'
  cat "$work/block.sh"
  echo 'printf "%s\n" "$remote"'
} > "$work/render.sh"
bash "$work/render.sh" | sed -n '/^free_mb=/,/^fi$/p' > "$work/gate.sh"
[ -s "$work/gate.sh" ] || { echo "FAIL: no disk gate in the rendered roll script"; exit 1; }

mkdir -p "$work/bin"
gate() {
  printf '#!/bin/sh\necho Avail\necho %s\n' "$(($1 * 1024))" > "$work/bin/df"
  chmod +x "$work/bin/df"
  PATH="$work/bin:$PATH" bash -c "set -euo pipefail; source '$work/gate.sh'; echo PULLED" 2>&1
}

case "$(gate 2048)" in
  *"deploy refused"*) case "$(gate 2048)" in
      *PULLED*) report FAIL "2048 MB free: refused but went on to the pull" ;;
      *) report PASS "2048 MB free: refused before the pull" ;;
    esac ;;
  *) report FAIL "2048 MB free: not refused" ;;
esac
case "$(gate 3072)" in
  *PULLED*) report PASS "3072 MB free: the pull runs" ;;
  *) report FAIL "3072 MB free: refused at the limit" ;;
esac
case "$(gate 3071)" in
  *"deploy refused"*) report PASS "3071 MB free: refused just under the limit" ;;
  *) report FAIL "3071 MB free: not refused" ;;
esac

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
