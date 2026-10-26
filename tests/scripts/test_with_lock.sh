#!/usr/bin/env bash
# Proves scripts/with-lock.sh: two holders never overlap, a holder sent TERM
# releases the lock only once its command is dead, and a waiter that times out
# exits 75 without touching the holder's lock. Run by hand:
#   bash tests/scripts/test_with_lock.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
with_lock=$root/scripts/with-lock.sh
work=$(mktemp -d "${TMPDIR:-/tmp}/with-lock-test.XXXXXX")
lock=$work/lock
holder=""
fails=0

cleanup() {
  [ -z "$holder" ] || kill -TERM "$holder" 2>/dev/null || true
  rm -rf "$work"
}
trap cleanup EXIT

report() {
  echo "$1: $2"
  [ "$1" = PASS ] || fails=$((fails + 1))
}

# Polls until the holder has written its owner file (the trap is installed by
# then), so a signal sent afterwards is handled rather than lost.
wait_for_owner() {
  for _ in $(seq 1 50); do
    [ -f "$lock/owner" ] && return 0
    sleep 0.1
  done
  return 1
}

# (a) Two holders in parallel, each sleeping 1 s before stamping the time:
# serialized, the stamps are at least 1 s apart.
out=$work/out
stamp='sleep 1; python3 -c "import time; print(time.time_ns())" >> "$OUT"'
OUT=$out "$with_lock" "$lock" 10 -- sh -c "$stamp" &
a=$!
OUT=$out "$with_lock" "$lock" 10 -- sh -c "$stamp" &
b=$!
rc_a=0
rc_b=0
wait "$a" || rc_a=$?
wait "$b" || rc_b=$?
if [ "$rc_a" -eq 0 ] && [ "$rc_b" -eq 0 ] && [ "$(wc -l <"$out")" -eq 2 ]; then
  t1=$(sed -n 1p "$out")
  t2=$(sed -n 2p "$out")
  gap=$((t2 - t1))
  [ "$gap" -lt 0 ] && gap=$((-gap))
  if [ "$gap" -ge 1000000000 ]; then
    report PASS "two parallel holders are serialized (stamps ${gap} ns apart)"
  else
    report FAIL "two parallel holders overlapped (stamps ${gap} ns apart)"
  fi
else
  report FAIL "two parallel holders: exit codes $rc_a/$rc_b, $(cat "$out" 2>/dev/null | wc -l | tr -d ' ') stamps"
fi

# (b) A holder sent TERM releases the lock within 3 s, and its command is
# gone by the time another holder acquires.
pidfile=$work/pid
PIDFILE=$pidfile "$with_lock" "$lock" 10 -- sh -c 'echo $$ > "$PIDFILE"; exec sleep 30' &
holder=$!
if wait_for_owner; then
  kill -TERM "$holder"
  if "$with_lock" "$lock" 3 -- true; then
    if kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      report FAIL "holder sent TERM released the lock while its command still ran"
    else
      report PASS "holder sent TERM releases the lock within 3 s"
    fi
  else
    report FAIL "holder sent TERM did not release the lock within 3 s"
  fi
else
  report FAIL "holder sent TERM: holder never acquired the lock"
fi
wait "$holder" 2>/dev/null || true
holder=""

# (c) A waiter that times out exits 75 and leaves the holder's lock intact.
"$with_lock" "$lock" 10 -- sleep 30 &
holder=$!
if wait_for_owner; then
  rc=0
  "$with_lock" "$lock" 1 -- true || rc=$?
  if [ "$rc" -eq 75 ] && [ -d "$lock" ]; then
    report PASS "waiter times out with exit 75 and leaves the lock"
  else
    report FAIL "waiter timeout: exit $rc, lock present: $([ -d "$lock" ] && echo yes || echo no)"
  fi
else
  report FAIL "waiter timeout: holder never acquired the lock"
fi
kill -TERM "$holder" 2>/dev/null || true
wait "$holder" 2>/dev/null || true
holder=""

[ "$fails" -eq 0 ]
