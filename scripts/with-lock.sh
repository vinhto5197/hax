#!/usr/bin/env bash
# Runs one command under a directory lock so gate steps that share a resource
# never overlap: pytest on hax_test, and the e2e stack (hax_e2e, Redis db 15,
# ports 3001/8001/8787). The atomic primitive is creating <lockdir>/owner with
# noclobber, which bash opens O_CREAT|O_EXCL: the process that creates it
# holds the lock and records its pid and command there. Not `mkdir`: the Rust
# coreutils that Ubuntu 26.04 ships as `mkdir` lets two racing callers both
# succeed. Every other caller polls every 2 s until the lock is gone or
# <timeout-seconds> pass, then exits 75 (EX_TEMPFAIL). A holder removes the
# lock when its command ends or when the holder is sent INT or TERM; the
# command is signalled first and waited for, so the lock is never free while
# the command still runs. A lock left behind by kill -9 is stale and the
# operator's to remove by hand.
#
# usage: with-lock.sh <lockdir> <timeout-seconds> -- <command...>
set -euo pipefail

usage() {
  echo "usage: ${0##*/} <lockdir> <timeout-seconds> -- <command...>" >&2
  exit 64
}

[ $# -ge 4 ] && [ "$3" = "--" ] || usage
lockdir=$1
timeout=$2
shift 3
[ -n "$lockdir" ] || usage
case $timeout in '' | *[!0-9]*) usage ;; esac
parent=$(dirname "$lockdir")
[ -d "$parent" ] || {
  echo "${0##*/}: $parent: no such directory" >&2
  exit 64
}

SECONDS=0
until mkdir -p "$lockdir" 2>/dev/null &&
  (set -o noclobber && echo "$$ $*" >"$lockdir/owner") 2>/dev/null; do
  if [ "$SECONDS" -ge "$timeout" ]; then
    owner=$(cat "$lockdir/owner" 2>/dev/null || echo unknown)
    echo "${0##*/}: timed out after ${timeout}s waiting for $lockdir (owner: $owner)" >&2
    exit 75
  fi
  sleep 2
done

# The lock is ours from here. The trap is installed only now: a waiter that
# gave up must never remove another holder's lock.
child=""
cleanup() {
  if [ -n "$child" ]; then
    kill -TERM "$child" 2>/dev/null || true
    wait "$child" 2>/dev/null || true
  fi
  rm -rf "$lockdir"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# The command runs as a background job that the script waits on: bash holds a
# trap back while a foreground child runs, so a TERM would otherwise sit until
# the command finished on its own. <&0 keeps stdin, which bash would point at
# /dev/null for a background job.
"$@" <&0 &
child=$!
status=0
wait "$child" || status=$?
child=""
exit "$status"
