#!/usr/bin/env bash
# Proves scripts/with-lock.sh against its signal and lock contract: a signal
# sent with kill reaches the command's whole process tree as the same signal
# (INT as INT, TERM as TERM, QUIT as QUIT); the lock is released only after the
# tree has finished its own cleanup (processes it forks meanwhile, orphaned
# subtrees included) or been killed after WITH_LOCK_GRACE, which is wall time
# and which a second signal cuts short; at a terminal, Ctrl-C reaches the
# command exactly once, Ctrl-\ reaches it, and it can read the terminal;
# holders never overlap; WITH_LOCK_POLL is honoured and racing waiters never
# fail a green run; a waiter that times out exits 75 without running its
# command or touching the holder's lock; statuses are 0/N/126/127/130/131/143/
# 75/64 as documented, malformed numbers included; stdin reaches the command.
# Run by hand:
#   bash tests/scripts/test_with_lock.sh
#
# Wrappers sent a signal are started through perl, which restores INT and QUIT
# to their defaults before exec: a non-interactive shell starts background jobs
# with INT ignored, and a signal ignored at entry cannot be trapped, so without
# this the INT cases would test the harness rather than the wrapper.
set -uo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
with_lock=$root/scripts/with-lock.sh
work=$(mktemp -d "${TMPDIR:-/tmp}/with-lock-test.XXXXXX")
. "$root/tests/scripts/lib.sh"
bg_env=""
bg_shell=""

# Every pid this test starts, or that a command it started records, is written
# to a *.pid file under $work; cleanup kills exactly those.
cleanup() {
  local f p
  for f in "$work"/*.pid "$work"/*/*.pid; do
    [ -f "$f" ] || continue
    p=$(cat "$f" 2>/dev/null) || continue
    [ -n "$p" ] || continue
    kill -TERM "$p" 2>/dev/null || true
  done
  # Give wrappers time to take their own trees down before anything is KILLed:
  # a wrapper KILLed mid-shutdown orphans its command.
  local i=0 alive
  while [ "$i" -lt 30 ]; do
    alive=no
    for f in "$work"/*.pid "$work"/*/*.pid; do
      [ -f "$f" ] || continue
      p=$(cat "$f" 2>/dev/null) || continue
      [ -n "$p" ] && kill -0 "$p" 2>/dev/null && alive=yes
    done
    [ "$alive" = no ] && break
    sleep 0.1
    i=$((i + 1))
  done
  for f in "$work"/*.pid "$work"/*/*.pid; do
    [ -f "$f" ] || continue
    p=$(cat "$f" 2>/dev/null) || continue
    [ -n "$p" ] || continue
    kill -KILL "$p" 2>/dev/null || true
  done
  rm -rf "$work"
}
trap cleanup EXIT

# wait_for_file <path> <tenths-of-a-second>
wait_for_file() {
  local i=0
  while [ "$i" -lt "$2" ]; do
    [ -e "$1" ] && return 0
    sleep 0.1
    i=$((i + 1))
  done
  return 1
}

# wait_gone <path> <tenths-of-a-second>
wait_gone() {
  local i=0
  while [ "$i" -lt "$2" ]; do
    [ -e "$1" ] || return 0
    sleep 0.1
    i=$((i + 1))
  done
  return 1
}

# dead <pid> <tenths-of-a-second>: true once the pid no longer exists.
dead() {
  local i=0
  while [ "$i" -lt "$2" ]; do
    kill -0 "$1" 2>/dev/null || return 0
    sleep 0.1
    i=$((i + 1))
  done
  return 1
}

# start_bg <name> <lockdir> <timeout> -- <command...>
# Starts a wrapper in the background with $bg_env in its environment; its pid
# lands in $work/<name>.pid and, when it exits, its status in $work/<name>.rc.
start_bg() {
  local name=$1
  shift
  (
    # shellcheck disable=SC2086
    env $bg_env perl -e '$SIG{INT}="DEFAULT"; $SIG{QUIT}="DEFAULT"; exec @ARGV or die "exec: $!\n"' \
      $bg_shell "$with_lock" "$@" </dev/null &
    echo $! >"$work/$name.pid"
    wait $!
    echo $? >"$work/$name.rc"
  ) &
  echo $! >"$work/$name-sub.pid"
  wait_for_file "$work/$name.pid" 50
}

# rc_of <name> <tenths>: prints the wrapper's exit status, or "timeout".
rc_of() {
  if wait_for_file "$work/$1.rc" "$2"; then
    cat "$work/$1.rc"
  else
    echo timeout
  fi
}

# A command that traps INT and TERM separately, records which one it got, and
# exits; "ready" appears once both traps are installed.
trap_cmd='trap "echo INT >\"$1/got\"; exit 0" INT; trap "echo TERM >\"$1/got\"; exit 0" TERM; echo $$ >"$1/cmd.pid"; : >"$1/ready"; while :; do sleep 0.1; done'

# 1 ---------------------------------------------------------------------------
d=$work/c1
mkdir -p "$d"
lock=$d/lock
start_bg c1 "$lock" 5 -- sh -c 'sleep 300 & echo $! >"$1/grandchild.pid"; wait' sh "$d"
if wait_for_file "$d/grandchild.pid" 50 && wait_for_file "$lock/owner" 50; then
  sleep 0.2
  kill -TERM "$(cat "$work/c1.pid")"
  WITH_LOCK_POLL=0.05 "$with_lock" "$lock" 15 -- \
    sh -c 'if kill -0 "$(cat "$1")" 2>/dev/null; then exit 1; fi; exit 0' sh "$d/grandchild.pid"
  rc=$?
  if [ "$rc" = 0 ]; then
    report PASS "TERM to the wrapper kills a grandchild of a non-exec'd compound command before the lock is free"
  else
    report FAIL "TERM to the wrapper kills a grandchild of a non-exec'd compound command before the lock is free (next holder saw it alive or failed: status $rc)"
  fi
else
  report FAIL "TERM to the wrapper kills a grandchild of a non-exec'd compound command before the lock is free (command never started)"
fi

# 2 ---------------------------------------------------------------------------
d=$work/c2
mkdir -p "$d"
start_bg c2 "$d/lock" 5 -- sh -c "$trap_cmd" sh "$d"
if wait_for_file "$d/ready" 50; then
  kill -INT "$(cat "$work/c2.pid")"
  rc=$(rc_of c2 150)
  got=$(cat "$d/got" 2>/dev/null || echo none)
  if [ "$got" = INT ] && [ "$rc" = 130 ]; then
    report PASS "INT to the wrapper reaches the command as INT and the wrapper exits 130"
  else
    report FAIL "INT to the wrapper reaches the command as INT and the wrapper exits 130 (command got $got, wrapper status $rc)"
  fi
else
  report FAIL "INT to the wrapper reaches the command as INT and the wrapper exits 130 (command never started)"
fi

# 3 ---------------------------------------------------------------------------
d=$work/c3
mkdir -p "$d"
start_bg c3 "$d/lock" 5 -- sh -c "$trap_cmd" sh "$d"
if wait_for_file "$d/ready" 50; then
  kill -TERM "$(cat "$work/c3.pid")"
  rc=$(rc_of c3 150)
  got=$(cat "$d/got" 2>/dev/null || echo none)
  if [ "$got" = TERM ] && [ "$rc" = 143 ]; then
    report PASS "TERM to the wrapper reaches the command as TERM and the wrapper exits 143"
  else
    report FAIL "TERM to the wrapper reaches the command as TERM and the wrapper exits 143 (command got $got, wrapper status $rc)"
  fi
else
  report FAIL "TERM to the wrapper reaches the command as TERM and the wrapper exits 143 (command never started)"
fi

# 4 ---------------------------------------------------------------------------
d=$work/c4
mkdir -p "$d"
lock=$d/lock
start_bg c4 "$lock" 5 -- \
  sh -c 'trap "sleep 1; : >\"$1/marker\"; exit 0" TERM; echo $$ >"$1/cmd.pid"; : >"$1/ready"; while :; do sleep 0.1; done' sh "$d"
if wait_for_file "$d/ready" 50 && wait_for_file "$lock/owner" 50; then
  kill -TERM "$(cat "$work/c4.pid")"
  WITH_LOCK_POLL=0.05 "$with_lock" "$lock" 15 -- test -f "$d/marker"
  rc=$?
  if [ "$rc" = 0 ]; then
    report PASS "the lock is released only after a signalled command finishes its own cleanup"
  else
    report FAIL "the lock is released only after a signalled command finishes its own cleanup (next holder status $rc)"
  fi
else
  report FAIL "the lock is released only after a signalled command finishes its own cleanup (command never started)"
fi

# 5 ---------------------------------------------------------------------------
d=$work/c5
mkdir -p "$d"
lock=$d/lock
bg_env="WITH_LOCK_GRACE=1"
start_bg c5 "$lock" 5 -- sh -c '
  trap "" INT TERM
  sh -c "trap \"\" INT TERM; echo \$\$ >\"\$1/grandchild.pid\"; while :; do sleep 0.1; done" sh "$1" &
  echo $$ >"$1/cmd.pid"
  while :; do sleep 0.1; done' sh "$d"
bg_env=""
if wait_for_file "$d/grandchild.pid" 50 && wait_for_file "$d/cmd.pid" 50 && wait_for_file "$lock/owner" 50; then
  sleep 0.2
  kill -TERM "$(cat "$work/c5.pid")"
  rc=$(rc_of c5 50)
  cmd_dead=no
  gc_dead=no
  dead "$(cat "$d/cmd.pid")" 20 && cmd_dead=yes
  dead "$(cat "$d/grandchild.pid")" 20 && gc_dead=yes
  lock_free=no
  [ -e "$lock" ] || lock_free=yes
  if [ "$rc" = 143 ] && [ "$cmd_dead" = yes ] && [ "$gc_dead" = yes ] && [ "$lock_free" = yes ]; then
    report PASS "a command tree that ignores INT and TERM is killed after WITH_LOCK_GRACE and the wrapper exits 143 with the lock free"
  else
    report FAIL "a command tree that ignores INT and TERM is killed after WITH_LOCK_GRACE and the wrapper exits 143 with the lock free (status $rc within 5s, command dead $cmd_dead, grandchild dead $gc_dead, lock free $lock_free)"
  fi
else
  report FAIL "a command tree that ignores INT and TERM is killed after WITH_LOCK_GRACE and the wrapper exits 143 with the lock free (command never started)"
fi

# 6 ---------------------------------------------------------------------------
d=$work/c6
mkdir -p "$d"
"$with_lock" "$d/lock" 5 -- true </dev/null
rc=$?
if [ "$rc" = 0 ] && [ ! -e "$d/lock" ]; then
  report PASS "a command that succeeds returns 0 and leaves no lock dir"
else
  report FAIL "a command that succeeds returns 0 and leaves no lock dir (status $rc)"
fi
"$with_lock" "$d/lock" 5 -- sh -c 'exit 3' </dev/null
rc=$?
if [ "$rc" = 3 ] && [ ! -e "$d/lock" ]; then
  report PASS "a command that exits 3 returns 3 and leaves no lock dir"
else
  report FAIL "a command that exits 3 returns 3 and leaves no lock dir (status $rc)"
fi

# 7 ---------------------------------------------------------------------------
d=$work/c7
mkdir -p "$d"
for n in a b; do
  (
    bad=0
    i=0
    while [ "$i" -lt 100 ]; do
      WITH_LOCK_POLL=0.01 "$with_lock" "$d/lock" 60 -- true </dev/null || bad=$((bad + 1))
      i=$((i + 1))
    done
    echo "$bad" >"$d/$n.bad"
  ) &
  echo $! >"$work/c7-$n.pid"
done
ok=yes
for n in a b; do
  wait "$(cat "$work/c7-$n.pid")" 2>/dev/null
  bad=$(cat "$d/$n.bad" 2>/dev/null || echo missing)
  [ "$bad" = 0 ] || ok="no (loop $n: $bad non-zero)"
done
if [ "$ok" = yes ]; then
  report PASS "two loops of 100 racing wrappers running true all exit 0"
else
  report FAIL "two loops of 100 racing wrappers running true all exit 0 ($ok)"
fi

# 8 ---------------------------------------------------------------------------
d=$work/c8
mkdir -p "$d"
: >"$d/log"
for n in 1 2 3 4 5; do
  (
    WITH_LOCK_POLL=0.05 "$with_lock" "$d/lock" 30 -- \
      sh -c 'echo start >>"$1"; sleep 0.2; echo end >>"$1"' sh "$d/log" </dev/null
  ) &
  echo $! >"$work/c8-$n.pid"
done
for n in 1 2 3 4 5; do
  wait "$(cat "$work/c8-$n.pid")" 2>/dev/null
done
expected=$(for _ in 1 2 3 4 5; do printf 'start\nend\n'; done)
if [ "$(cat "$d/log")" = "$expected" ]; then
  report PASS "holders never overlap: the shared log strictly alternates start and end"
else
  report FAIL "holders never overlap: the shared log strictly alternates start and end (got: $(tr '\n' ' ' <"$d/log"))"
fi

# 9 ---------------------------------------------------------------------------
d=$work/c9
mkdir -p "$d"
lock=$d/lock
start_bg c9 "$lock" 5 -- sleep 5
if wait_for_file "$lock/owner" 50; then
  sleep 0.2
  before=$(cat "$lock/owner")
  WITH_LOCK_POLL=0.05 "$with_lock" "$lock" 1 -- true </dev/null
  rc=$?
  after=$(cat "$lock/owner" 2>/dev/null || echo missing)
  owner_pid=${before%% *}
  if [ "$rc" = 75 ] && [ "$after" = "$before" ] && kill -0 "$owner_pid" 2>/dev/null; then
    report PASS "a waiter that times out exits 75 and leaves the holder's owner file as it was"
  else
    report FAIL "a waiter that times out exits 75 and leaves the holder's owner file as it was (status $rc, owner before '$before', after '$after')"
  fi
else
  report FAIL "a waiter that times out exits 75 and leaves the holder's owner file as it was (holder never took the lock)"
fi
kill -TERM "$(cat "$work/c9.pid")" 2>/dev/null || true
rc_of c9 50 >/dev/null

# 10 --------------------------------------------------------------------------
d=$work/c10
mkdir -p "$d"
out=$(printf 'hi\n' | "$with_lock" "$d/lock" 5 -- cat)
if [ "$out" = hi ]; then
  report PASS "the wrapper's stdin reaches the command"
else
  report FAIL "the wrapper's stdin reaches the command (got '$out')"
fi

# 11 --------------------------------------------------------------------------
d=$work/c11
mkdir -p "$d"
"$with_lock" "$d/lock" 5 true </dev/null 2>/dev/null
rc=$?
if [ "$rc" = 64 ]; then
  report PASS "usage without -- exits 64"
else
  report FAIL "usage without -- exits 64 (status $rc)"
fi
"$with_lock" "$d/lock" abc -- true </dev/null 2>/dev/null
rc=$?
if [ "$rc" = 64 ]; then
  report PASS "a non-numeric timeout exits 64"
else
  report FAIL "a non-numeric timeout exits 64 (status $rc)"
fi

# 12 --------------------------------------------------------------------------
d=$work/c12
mkdir -p "$d"
lock=$d/lock
start_bg c12 "$lock" 5 -- sleep 5
if wait_for_file "$lock/owner" 50; then
  sleep 0.2
  WITH_LOCK_POLL=0.05 "$with_lock" "$lock" 1 -- sh -c ': >"$1"' sh "$d/marker" </dev/null 2>/dev/null
  rc=$?
  if [ "$rc" = 75 ] && [ ! -e "$d/marker" ]; then
    report PASS "a waiter that times out never runs its command"
  else
    report FAIL "a waiter that times out never runs its command (status $rc, marker present: $([ -e "$d/marker" ] && echo yes || echo no))"
  fi
else
  report FAIL "a waiter that times out never runs its command (holder never took the lock)"
fi
kill -TERM "$(cat "$work/c12.pid")" 2>/dev/null || true
rc_of c12 50 >/dev/null

# 13 --------------------------------------------------------------------------
d=$work/c13
mkdir -p "$d"
lock=$d/lock
bg_env="WITH_LOCK_GRACE=30"
start_bg c13 "$lock" 5 -- sh -c '
  trap "" TERM
  sh -c "trap \"\" TERM; echo \$\$ >\"\$1/grandchild.pid\"; while :; do sleep 0.1; done" sh "$1" &
  echo $$ >"$1/cmd.pid"
  while :; do sleep 0.1; done' sh "$d"
bg_env=""
if wait_for_file "$d/grandchild.pid" 50 && wait_for_file "$d/cmd.pid" 50 && wait_for_file "$lock/owner" 50; then
  sleep 0.2
  kill -TERM "$(cat "$work/c13.pid")"
  sleep 1
  kill -TERM "$(cat "$work/c13.pid")" 2>/dev/null
  rc=$(rc_of c13 35)
  cmd_dead=no
  gc_dead=no
  dead "$(cat "$d/cmd.pid")" 20 && cmd_dead=yes
  dead "$(cat "$d/grandchild.pid")" 20 && gc_dead=yes
  lock_free=no
  [ -e "$lock" ] || lock_free=yes
  if [ "$rc" = 143 ] && [ "$cmd_dead" = yes ] && [ "$gc_dead" = yes ] && [ "$lock_free" = yes ]; then
    report PASS "a second TERM during the grace period cuts it short, kills the tree and frees the lock"
  else
    report FAIL "a second TERM during the grace period cuts it short, kills the tree and frees the lock (status $rc within 3.5s of the second TERM, command dead $cmd_dead, grandchild dead $gc_dead, lock free $lock_free)"
  fi
else
  report FAIL "a second TERM during the grace period cuts it short, kills the tree and frees the lock (command never started)"
fi

# 14 --------------------------------------------------------------------------
d=$work/c14
mkdir -p "$d"
lock=$d/lock
bg_env="WITH_LOCK_GRACE=2"
start_bg c14 "$lock" 5 -- \
  sh -c 'trap "sleep 20 & echo \$! >\"\$1/late.pid\"; sleep 1; exit 0" TERM; echo $$ >"$1/cmd.pid"; : >"$1/ready"; while :; do sleep 0.1; done' sh "$d"
bg_env=""
if wait_for_file "$d/ready" 50 && wait_for_file "$lock/owner" 50; then
  kill -TERM "$(cat "$work/c14.pid")"
  WITH_LOCK_POLL=0.05 "$with_lock" "$lock" 30 -- \
    sh -c '[ -s "$1" ] || exit 2; if kill -0 "$(cat "$1")" 2>/dev/null; then exit 1; fi; exit 0' sh "$d/late.pid" </dev/null
  rc=$?
  if [ "$rc" = 0 ]; then
    report PASS "a process forked by the command's TERM handler, which runs on for 1s, is dead before the next holder runs"
  else
    report FAIL "a process forked by the command's TERM handler, which runs on for 1s, is dead before the next holder runs (next holder status $rc: 1 = alive, 2 = never forked)"
  fi
else
  report FAIL "a process forked by the command's TERM handler, which runs on for 1s, is dead before the next holder runs (command never started)"
fi

# 15-17: the wrapper as the foreground job of a pseudo-terminal --------------
# pty_run <cwd> <ready-file> <input> <output-file> <timeout> -- <argv...>
# Spawns argv on a new pty (it becomes the session leader and the foreground
# group), waits for <ready-file>, writes <input> (Python escapes, e.g. \x03;
# "<pause>" between two pieces waits 0.7 s), records the time of the last write
# in <output-file>.sent, then collects output until argv exits. Exits with
# argv's status (128+N when killed by signal N), or 124 after <timeout>
# seconds, having KILLed the pty's process group, so a wedged case fails
# instead of hanging the suite.
pty_py=$work/pty_run.py
cat >"$pty_py" <<'PY'
import os, pty, select, signal, sys, time
cwd, ready, data, out_path, timeout = sys.argv[1:6]
argv = sys.argv[7:]
pieces = [p.encode().decode("unicode_escape").encode("latin-1") for p in data.split("<pause>")]
deadline = time.time() + float(timeout)
pid, fd = pty.fork()
if pid == 0:
    os.chdir(cwd)
    for s in (signal.SIGINT, signal.SIGQUIT, signal.SIGTERM):
        signal.signal(s, signal.SIG_DFL)
    os.execvp(argv[0], argv)
out = bytearray()
def pump(wait):
    r, _, _ = select.select([fd], [], [], wait)
    if r:
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            return False
        if not chunk:
            return False
        out.extend(chunk)
    return True
status = None
while not os.path.exists(ready) and time.time() < deadline:
    pump(0.05)
    done, st = os.waitpid(pid, os.WNOHANG)
    if done:
        status = st
        break
if status is None and time.time() < deadline:
    time.sleep(0.2)
    for n, piece in enumerate(pieces):
        if n:
            until = time.time() + 0.7
            while time.time() < until:
                pump(0.05)
        os.write(fd, piece)
    with open(out_path + ".sent", "w") as f:
        f.write(repr(time.time()))
while status is None and time.time() < deadline:
    pump(0.05)
    done, st = os.waitpid(pid, os.WNOHANG)
    if done:
        status = st
if status is None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass
    os.waitpid(pid, 0)
    code = 124
else:
    while pump(0.05):
        pass
    code = 128 + os.WTERMSIG(status) if os.WIFSIGNALED(status) else os.WEXITSTATUS(status)
with open(out_path, "wb") as f:
    f.write(bytes(out))
sys.exit(code)
PY

# 15 --------------------------------------------------------------------------
d=$work/c15
mkdir -p "$d"
lock=$d/lock
python3 "$pty_py" "$d" "$d/ready" '\x03' "$d/out" 10 -- \
  bash -c 'exec "$0" "$@"' "$with_lock" "$lock" 10 -- \
  sh -c 'trap "echo INT >>\"\$1/ints\"" INT; echo $$ >"$1/cmd.pid"; : >"$1/ready"; while [ ! -s "$1/ints" ]; do sleep 0.05; done; sleep 0.5; exit 0' sh "$d"
rc=$?
ints=$(grep -c INT "$d/ints" 2>/dev/null || echo 0)
lock_free=no
[ -e "$lock" ] || lock_free=yes
if [ "$ints" = 1 ] && [ "$rc" = 130 ] && [ "$lock_free" = yes ]; then
  report PASS "Ctrl-C at a terminal reaches the command exactly once, the wrapper exits 130 and the lock is free"
else
  report FAIL "Ctrl-C at a terminal reaches the command exactly once, the wrapper exits 130 and the lock is free (INTs seen $ints, status $rc (124 = timed out), lock free $lock_free)"
fi

# 16 --------------------------------------------------------------------------
d=$work/c16
mkdir -p "$d"
lock=$d/lock
python3 "$pty_py" "$d" "$d/ready" '\x1c' "$d/out" 10 -- \
  bash -c 'exec "$0" "$@"' "$with_lock" "$lock" 10 -- \
  sh -c 'trap ": >\"\$1/quit\"; exit 0" QUIT; echo $$ >"$1/cmd.pid"; : >"$1/ready"; while :; do sleep 0.1; done' sh "$d"
rc=$?
quit=no
[ -e "$d/quit" ] && quit=yes
lock_free=no
[ -e "$lock" ] || lock_free=yes
if [ "$quit" = yes ] && [ "$rc" = 131 ] && [ "$lock_free" = yes ]; then
  report PASS "Ctrl-\\ at a terminal reaches the command, the wrapper exits 131 and the lock is free"
else
  report FAIL "Ctrl-\\ at a terminal reaches the command, the wrapper exits 131 and the lock is free (QUIT marker $quit, status $rc (124 = timed out), lock free $lock_free)"
fi

# 17 --------------------------------------------------------------------------
d=$work/c17
mkdir -p "$d"
lock=$d/lock
python3 "$pty_py" "$d" "$lock/owner" 'hi\r' "$d/out" 3 -- \
  bash -c 'exec "$0" "$@"' "$with_lock" "$lock" 10 -- \
  sh -c 'read x; echo "got $x"'
rc=$?
if grep -q 'got hi' "$d/out" 2>/dev/null && [ "$rc" = 0 ]; then
  report PASS "a command run at a terminal can read the terminal"
else
  report FAIL "a command run at a terminal can read the terminal (status $rc (124 = timed out), output: $(tr '\r\n' '  ' <"$d/out" 2>/dev/null))"
fi

# 18 --------------------------------------------------------------------------
d=$work/c18
mkdir -p "$d"
lock=$d/lock
stamp='import sys, time; open(sys.argv[1], "w").write(repr(time.time()))'
start_bg c18 "$lock" 10 -- sh -c 'sleep 1; python3 -c "$1" "$2"' sh "$stamp" "$d/end"
if wait_for_file "$lock/owner" 50; then
  WITH_LOCK_POLL=0.05 "$with_lock" "$lock" 10 -- python3 -c "$stamp" "$d/start" </dev/null
  rc=$?
  gap=$(python3 -c 'import sys; print("%.3f" % (float(open(sys.argv[2]).read()) - float(open(sys.argv[1]).read())))' "$d/end" "$d/start" 2>/dev/null || echo unknown)
  if [ "$rc" = 0 ] && python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) < 0.5 else 1)' "$gap" 2>/dev/null; then
    report PASS "a waiter with WITH_LOCK_POLL=0.05 starts within 0.5s of the holder ending"
  else
    report FAIL "a waiter with WITH_LOCK_POLL=0.05 starts within 0.5s of the holder ending (status $rc, gap ${gap}s)"
  fi
else
  report FAIL "a waiter with WITH_LOCK_POLL=0.05 starts within 0.5s of the holder ending (holder never took the lock)"
fi
rc_of c18 50 >/dev/null

# 19 --------------------------------------------------------------------------
d=$work/c19
mkdir -p "$d"
for spec in 'WITH_LOCK_POLL=.' 'WITH_LOCK_POLL=1.' 'WITH_LOCK_GRACE=abc'; do
  env "$spec" "$with_lock" "$d/lock" 5 -- true </dev/null 2>/dev/null
  rc=$?
  if [ "$rc" = 64 ]; then
    report PASS "$spec is bad usage and exits 64"
  else
    report FAIL "$spec is bad usage and exits 64 (status $rc)"
  fi
done

# 20 --------------------------------------------------------------------------
d=$work/c20
mkdir -p "$d"
lock=$d/lock
start_bg c20 "$lock" 5 -- \
  sh -c 'trap "echo QUIT >\"\$1/got\"; exit 0" QUIT; echo $$ >"$1/cmd.pid"; : >"$1/ready"; while :; do sleep 0.1; done' sh "$d"
if wait_for_file "$d/ready" 50; then
  kill -QUIT "$(cat "$work/c20.pid")"
  rc=$(rc_of c20 150)
  got=$(cat "$d/got" 2>/dev/null || echo none)
  lock_free=no
  [ -e "$lock" ] || lock_free=yes
  if [ "$got" = QUIT ] && [ "$rc" = 131 ] && [ "$lock_free" = yes ]; then
    report PASS "QUIT sent to the wrapper by kill reaches the command as QUIT, the wrapper exits 131 and the lock is free"
  else
    report FAIL "QUIT sent to the wrapper by kill reaches the command as QUIT, the wrapper exits 131 and the lock is free (command got $got, wrapper status $rc, lock free $lock_free)"
  fi
else
  report FAIL "QUIT sent to the wrapper by kill reaches the command as QUIT, the wrapper exits 131 and the lock is free (command never started)"
fi

# 21 --------------------------------------------------------------------------
d=$work/c21
mkdir -p "$d"
lock=$d/lock
bg_env="WITH_LOCK_GRACE=5"
start_bg c21 "$lock" 5 -- sh -c '
  (
    trap "sleep 60 & echo \$! >\"\$1/late.pid\"; sleep 1; exit 0" TERM
    : >"$1/ready"
    while :; do sleep 0.1; done
  ) &
  echo $! >"$1/sub.pid"
  echo $$ >"$1/cmd.pid"
  wait' sh "$d"
bg_env=""
if wait_for_file "$d/ready" 50 && wait_for_file "$d/sub.pid" 50 && wait_for_file "$lock/owner" 50; then
  sleep 0.2
  kill -TERM "$(cat "$work/c21.pid")"
  WITH_LOCK_POLL=0.05 "$with_lock" "$lock" 30 -- \
    sh -c '[ -s "$1" ] || exit 2; if kill -0 "$(cat "$1")" 2>/dev/null; then exit 1; fi; exit 0' sh "$d/late.pid" </dev/null
  rc=$?
  if [ "$rc" = 0 ]; then
    report PASS "a process forked later by an orphaned subtree is dead before the next holder runs"
  else
    report FAIL "a process forked later by an orphaned subtree is dead before the next holder runs (next holder status $rc: 1 = alive, 2 = never forked)"
  fi
else
  report FAIL "a process forked later by an orphaned subtree is dead before the next holder runs (command never started)"
fi

# 22 --------------------------------------------------------------------------
d=$work/c22
mkdir -p "$d"
"$with_lock" "$d/lock" 5 -- "hax-no-such-command-$$" </dev/null 2>/dev/null
rc=$?
if [ "$rc" = 127 ] && [ ! -e "$d/lock" ]; then
  report PASS "a missing command exits 127 and leaves the lock free"
else
  report FAIL "a missing command exits 127 and leaves the lock free (status $rc, lock dir present: $([ -e "$d/lock" ] && echo yes || echo no))"
fi
printf '#!/bin/sh\nexit 0\n' >"$d/not-executable"
chmod 644 "$d/not-executable"
"$with_lock" "$d/lock" 5 -- "$d/not-executable" </dev/null 2>/dev/null
rc=$?
if [ "$rc" = 126 ] && [ ! -e "$d/lock" ]; then
  report PASS "a command without execute permission exits 126 and leaves the lock free"
else
  report FAIL "a command without execute permission exits 126 and leaves the lock free (status $rc, lock dir present: $([ -e "$d/lock" ] && echo yes || echo no))"
fi

# 23 --------------------------------------------------------------------------
d=$work/c23
mkdir -p "$d"
lock=$d/lock
bg_env="WITH_LOCK_GRACE=2"
start_bg c23 "$lock" 5 -- sh -c '
  trap "" TERM
  i=0
  while [ "$i" -lt 29 ]; do
    sh -c "trap \"\" TERM; echo \$\$ >\"\$1/p$i.pid\"; while :; do sleep 0.1; done" sh "$1" &
    i=$((i + 1))
  done
  echo $$ >"$1/cmd.pid"
  while :; do sleep 0.1; done' sh "$d"
bg_env=""
started=yes
wait_for_file "$d/cmd.pid" 50 || started=no
wait_for_file "$lock/owner" 50 || started=no
i=0
while [ "$i" -lt 29 ]; do
  wait_for_file "$d/p$i.pid" 50 || started=no
  i=$((i + 1))
done
if [ "$started" = yes ]; then
  sleep 0.3
  kill -TERM "$(cat "$work/c23.pid")"
  if wait_gone "$lock" 35; then
    report PASS "with WITH_LOCK_GRACE=2 the lock is free within 3.5s of TERM for a 30-process tree that ignores TERM"
  else
    report FAIL "with WITH_LOCK_GRACE=2 the lock is free within 3.5s of TERM for a 30-process tree that ignores TERM (lock still held after 3.5s)"
  fi
else
  report FAIL "with WITH_LOCK_GRACE=2 the lock is free within 3.5s of TERM for a 30-process tree that ignores TERM (tree never started)"
fi
rc_of c23 150 >/dev/null

# 24 --------------------------------------------------------------------------
# The pty's session leader is a bash that outlives the wrapper, as a login
# shell does: a dead leader changes how the terminal delivers signals. It traps
# INT (so a Ctrl-C does not end it) and its children start with INT at default.
d=$work/c24
mkdir -p "$d"
lock=$d/lock
stamp='import sys, time; open(sys.argv[1], "w").write(repr(time.time()))'
WITH_LOCK_GRACE=30 python3 "$pty_py" "$d" "$d/ready" '\x03<pause>\x03' "$d/out" 15 -- \
  bash -c 'trap : INT QUIT; d=$1; s=$2; shift 2; "$@"; echo $? >"$d/rc"; python3 -c "$s" "$d/end"; sleep 1' \
  leader "$d" "$stamp" "$with_lock" "$lock" 10 -- \
  sh -c 'trap "" INT; echo $$ >"$1/cmd.pid"; : >"$1/ready"; while :; do sleep 0.1; done' sh "$d"
prc=$?
rc=$(cat "$d/rc" 2>/dev/null || echo none)
gap=$(python3 -c 'import sys; print("%.3f" % (float(open(sys.argv[2]).read()) - float(open(sys.argv[1]).read())))' "$d/out.sent" "$d/end" 2>/dev/null || echo unknown)
in_time=no
python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) < 3.5 else 1)' "$gap" 2>/dev/null && in_time=yes
cmd_dead=no
[ -s "$d/cmd.pid" ] && dead "$(cat "$d/cmd.pid")" 20 && cmd_dead=yes
lock_free=no
[ -e "$lock" ] || lock_free=yes
if [ "$rc" = 130 ] && [ "$in_time" = yes ] && [ "$cmd_dead" = yes ] && [ "$lock_free" = yes ]; then
  report PASS "a second Ctrl-C at a terminal ends the grace: the wrapper exits 130 within 3.5s, the command is dead and the lock is free"
else
  report FAIL "a second Ctrl-C at a terminal ends the grace: the wrapper exits 130 within 3.5s, the command is dead and the lock is free (wrapper status $rc, ${gap}s after the second Ctrl-C, command dead $cmd_dead, lock free $lock_free, pty status $prc (124 = timed out))"
fi

# 25 --------------------------------------------------------------------------
# second_int_case <label> <bash binary>
second_int_case() {
  local label=$1 name
  name=c25-$(echo "$1" | tr -c 'a-z0-9' '-')
  d=$work/$name
  mkdir -p "$d"
  lock=$d/lock
  bg_env="WITH_LOCK_GRACE=30"
  bg_shell=$2
  start_bg "$name" "$lock" 5 -- \
    sh -c 'trap "" INT; echo $$ >"$1/cmd.pid"; : >"$1/ready"; while :; do sleep 0.1; done' sh "$d"
  bg_env=""
  bg_shell=""
  if wait_for_file "$d/ready" 50 && wait_for_file "$lock/owner" 50; then
    kill -INT "$(cat "$work/$name.pid")"
    sleep 0.7
    kill -INT "$(cat "$work/$name.pid")" 2>/dev/null
    rc=$(rc_of "$name" 35)
    lock_free=no
    [ -e "$lock" ] || lock_free=yes
    if [ "$rc" = 130 ] && [ "$lock_free" = yes ]; then
      report PASS "a second INT by kill cuts the grace short: exit 130 within 3.5s and the lock is free ($label)"
    else
      report FAIL "a second INT by kill cuts the grace short: exit 130 within 3.5s and the lock is free ($label: status $rc, lock free $lock_free)"
    fi
  else
    report FAIL "a second INT by kill cuts the grace short: exit 130 within 3.5s and the lock is free ($label: command never started)"
  fi
  rc_of "$name" 50 >/dev/null
}
path_bash=$(command -v bash)
second_int_case "bash from PATH" "$path_bash"
if [ -x /bin/bash ] && ! cmp -s "$path_bash" /bin/bash; then
  second_int_case "/bin/bash" /bin/bash
else
  echo "note: /bin/bash is the same binary as the PATH bash; the case above covers it"
fi

# 26 --------------------------------------------------------------------------
# Static: the owner file is created with noclobber in the wrapper's own shell,
# never in a ( … ) subshell. A subshell resets trapped signals to their
# defaults, so a Ctrl-C between its O_EXCL open and its exit kills it and
# leaves an empty owner file that no trap removes and every later caller waits
# on; a race that narrow is not reachable by a timing test. Comment lines are
# skipped. The second check keeps the first from passing because the
# noclobber primitive vanished altogether.
code=$(grep -v '^[[:space:]]*#' "$with_lock")
if grep -Eq '\([^)]*(noclobber|set -C)' <<<"$code"; then
  report FAIL "the owner file is not created by a noclobber subshell (found: $(grep -E '\([^)]*(noclobber|set -C)' <<<"$code" | head -n 1))"
else
  report PASS "the owner file is not created by a noclobber subshell"
fi
if grep -Eq '(^|[;&|[:space:]])set (-C|-o noclobber)([;&|[:space:]]|$)' <<<"$code"; then
  report PASS "the wrapper takes the lock with noclobber (set -C or set -o noclobber)"
else
  report FAIL "the wrapper takes the lock with noclobber (set -C or set -o noclobber): no such line"
fi

finish
