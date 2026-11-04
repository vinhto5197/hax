#!/usr/bin/env bash
# Runs one command under a directory lock so gate steps that share a resource
# never overlap: pytest on hax_test, and the e2e stack (hax_e2e, Redis db 15,
# ports 3001/8001/8787). The atomic primitive is creating <lockdir>/owner with
# noclobber, which bash opens O_CREAT|O_EXCL: the process that creates it
# holds the lock and records its pid and command there. Not `mkdir`: the Rust
# coreutils that Ubuntu 26.04 ships as `mkdir` lets two racing callers both
# succeed. Every other caller polls every WITH_LOCK_POLL seconds (default 2)
# until the lock is gone or <timeout-seconds> pass, then exits 75
# (EX_TEMPFAIL). A holder removes the lock when its command ends or when the
# holder is sent INT, QUIT or TERM. On a signal, every process of the command
# (it and all its descendants, since `make e2e` runs a shell whose servers
# are grandchildren) gets that signal once: a terminal's Ctrl-C or Ctrl-\
# already reached the ones in the terminal's foreground group, so the wrapper
# sends it only to the rest. They get WITH_LOCK_GRACE seconds (default 10) to
# clean up before KILL, cut short by a second signal; the lock is freed only
# once all of them are gone. The command stays in the caller's process group
# so it can read the terminal (pdb, a prompt). A lock left behind by kill -9
# is stale and the operator's to remove by hand.
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
poll=${WITH_LOCK_POLL:-2}
grace=${WITH_LOCK_GRACE:-10}
for n in "$poll" "$grace"; do
  [[ $n =~ ^[0-9]+(\.[0-9]+)?$ ]] || usage
done
parent=$(dirname "$lockdir")
[ -d "$parent" ] || {
  echo "${0##*/}: $parent: no such directory" >&2
  exit 64
}

# The signal traps only record (a cleanup run nested inside a handler misses
# a second signal on bash 3.2), and are in place before the lock is taken, so
# there is no moment where the lock is held and a signal is not handled.
signal=""
cut=""
on_signal() { if [ -n "$signal" ]; then cut=1; else signal=$1; fi; }
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM
trap 'on_signal QUIT' QUIT
exit_for() { case $1 in INT) exit 130 ;; QUIT) exit 131 ;; *) exit 143 ;; esac; }

SECONDS=0
until mkdir -p "$lockdir" 2>/dev/null &&
  (set -o noclobber && echo "$$ $*" >"$lockdir/owner") 2>/dev/null; do
  [ -z "$signal" ] || exit_for "$signal"
  if [ "$SECONDS" -ge "$timeout" ]; then
    owner=$(cat "$lockdir/owner" 2>/dev/null || echo unknown)
    echo "${0##*/}: timed out after ${timeout}s waiting for $lockdir (owner: $owner)" >&2
    exit 75
  fi
  sleep "$poll"
done

# The lock is ours from here, and so is every error: nothing below may end
# the wrapper before the lock is released.
set +e
release() {
  # Ignored, not trapped: a third Ctrl-C must not kill the rm that frees it.
  trap '' INT QUIT TERM
  # A waiter may create the lock dir again the moment owner is gone, so the
  # dir is removed only if empty, and never treated as an error.
  rm -f "$lockdir/owner"
  rmdir "$lockdir" 2>/dev/null || true
}
trap release EXIT
[ -z "$signal" ] || exit_for "$signal"

# The live processes under any of the given roots, from one ps snapshot. The
# walk starts from every process still alive from the last walk, not only the
# command: once the command exits, its children are reparented to init and a
# walk from the command alone would lose what they fork during cleanup. Dead
# pids drop out, so a reused pid is never signalled.
live_tree() {
  ps -A -o pid= -o ppid= -o stat= | awk -v roots="$*" '
    { kids[$2] = kids[$2] " " $1; if ($3 !~ /^Z/) alive[$1] = 1 }
    END {
      n = split(roots, queue, " ")
      for (i = 1; i <= n; i++) {
        p = queue[i]
        if (p in out) continue
        out[p] = 1
        if (p in alive) printf "%s ", p
        m = split(kids[p], a, " ")
        for (j = 1; j <= m; j++) queue[++n] = a[j]
      }
    }'
}
now_tenths() { perl -MTime::HiRes=time -e 'printf "%d", time * 10'; }
# The processes that did not already get $signal from the terminal: TERM
# never comes from one; INT and QUIT do, to the terminal's foreground group,
# whenever the wrapper itself is in it.
not_signalled_by_tty() {
  local fg="" p
  case $signal in INT | QUIT)
    fg=$(ps -o tpgid= -p $$ 2>/dev/null | tr -d ' ')
    [ "$fg" = "$(ps -o pgid= -p $$ 2>/dev/null | tr -d ' ')" ] || fg=""
    ;;
  esac
  for p in "$@"; do
    [ -n "$fg" ] && [ "$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')" = "$fg" ] && continue
    echo "$p"
  done
}
# Sends $signal once, gives the tree the grace (cut short by a second signal),
# then KILLs whatever is left. A second Ctrl-C at the terminal reaches the
# wrapper's own ps and sleep too, so a walk that failed keeps the last list.
stop_tree() {
  local seen next deadline
  seen=$(live_tree "$child")
  # shellcheck disable=SC2046,SC2086
  kill -"$signal" $(not_signalled_by_tty $seen) 2>/dev/null
  deadline=$(($(now_tenths) + $(awk -v g="$grace" 'BEGIN { printf "%d", g * 10 }')))
  while [ -z "$cut" ] && [ -n "$seen" ] && [ "$(now_tenths)" -lt "$deadline" ]; do
    sleep 0.1
    # shellcheck disable=SC2086
    next=$(live_tree $seen) && seen=$next
  done
  # shellcheck disable=SC2086
  next=$(live_tree $seen $child) && seen=$next
  # shellcheck disable=SC2086
  [ -z "$seen" ] || kill -KILL $seen 2>/dev/null
  wait "$child" 2>/dev/null
}

# The command runs as a background job that the script waits on: bash holds a
# trap back while a foreground child runs, so a TERM would otherwise sit until
# the command finished on its own. bash starts a background job with INT and
# QUIT ignored, and an ignored INT never reaches pytest's teardown, so perl
# restores both before it execs the command. <&0 keeps stdin, which bash
# would point at /dev/null for a background job.
perl -e '$SIG{INT} = $SIG{QUIT} = "DEFAULT"; exec { $ARGV[0] } @ARGV; warn "with-lock.sh: $ARGV[0]: $!\n"; exit($!{ENOENT} ? 127 : 126)' "$@" <&0 &
child=$!
# `wait` returns early when a trapped signal arrives; the command may still
# be running then. A signal already recorded (during the fork) would not
# interrupt a `wait` that starts after it, so it is not waited on.
status=0
[ -n "$signal" ] || { wait "$child"; status=$?; }
if [ -n "$signal" ]; then
  stop_tree
  exit_for "$signal"
fi
exit "$status"
