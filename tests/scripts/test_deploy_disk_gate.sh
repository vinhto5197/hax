#!/usr/bin/env bash
# Proves deploy.sh's disk gate as the box receives it: the roll script is an
# unquoted heredoc, so the gate is rendered the way deploy.sh renders it
# (local expansion, escaped \$ left for the box) and then run against a fake
# df. Under 3072 MB free the roll stops before the pull; at or above, it goes
# on. The rendered script's order is checked too: the prune, then the gate,
# then the pull, with nothing that touches the running stack before the gate.
# Run by hand:
#   bash tests/scripts/test_deploy_disk_gate.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/deploy-disk-test.XXXXXX")
. "$root/tests/scripts/lib.sh"
trap 'rm -rf "$work"' EXIT

# The heredoc block, from "remote=$(cat <<REMOTE" to its closing ")".
awk '/^  remote=\$\(cat <<REMOTE/{f=1} f{print} f&&/^\)$/{exit}' \
  "$root/infra/deploy/deploy.sh" > "$work/block.sh"
{
  echo 'raw=x PY_IMAGE=p WEB_IMAGE=w'
  cat "$work/block.sh"
  echo 'printf "%s\n" "$remote"'
} > "$work/render.sh"
bash "$work/render.sh" > "$work/roll.sh"
sed -n '/^free_mb=/,/^fi$/p' "$work/roll.sh" > "$work/gate.sh"
[ -s "$work/gate.sh" ] || { echo "FAIL: no disk gate in the rendered roll script"; exit 1; }

# First line number of a command (comments skipped) in the rendered roll
# script matching an ERE, or empty.
line_of() { grep -nE "$1" "$work/roll.sh" | grep -vE '^[0-9]+:[[:space:]]*#' | head -1 | cut -d: -f1; }
gate_at=$(line_of '^free_mb=')
pull_at=$(line_of 'compose pull')
prune_at=$(line_of '^docker (image|system) prune')
# Touching the running stack: a compose verb that starts, stops or enters a
# container, a docker verb that stops or removes one, a rename, or a write
# to a file the running stack reads (the .new/.next staging files are not).
touch_at=$(line_of 'compose (up|run|down|rm|stop|restart|kill|exec)|docker (stop|rm|kill|restart)|^mv |(>|-o|tee) *(Caddyfile|images\.env|compose\.prod\.yml)([[:space:];&)]|$)')
if [ -n "$pull_at" ] && [ "$gate_at" -lt "$pull_at" ]; then
  report PASS "the disk gate runs before the pull"
else
  report FAIL "the disk gate (line $gate_at) is not before the pull (line ${pull_at:-none})"
fi
if [ -n "$prune_at" ] && [ "$prune_at" -lt "$gate_at" ]; then
  report PASS "images are pruned before the disk gate"
else
  report FAIL "no prune before the disk gate (line $gate_at)"
fi
if [ -z "$touch_at" ] || [ "$touch_at" -gt "$gate_at" ]; then
  report PASS "nothing touches the running stack before the disk gate"
else
  report FAIL "line $touch_at touches the running stack before the disk gate (line $gate_at)"
fi

mkdir -p "$work/bin"
gate() {
  printf '#!/bin/sh\necho Avail\necho %s\n' "$(($1 * 1024))" > "$work/bin/df"
  chmod +x "$work/bin/df"
  PATH="$work/bin:$PATH" bash -c "set -euo pipefail; source '$work/gate.sh'; echo PULLED" 2>&1
}

if gate 2048 > /dev/null; then
  report FAIL "2048 MB free: the refusal exits zero"
else
  report PASS "2048 MB free: the refusal exits non-zero"
fi
case "$(gate 2048)" in
  *"disk: 2048 MB free on /var/lib/docker"*) report PASS "2048 MB free: the free space is printed" ;;
  *) report FAIL "2048 MB free: no 'disk: 2048 MB free' line" ;;
esac

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

finish
