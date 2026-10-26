#!/usr/bin/env bash
# Proves scripts/feature-worktree.sh refuses an id that could leave
# .claude/worktrees/ (".." would otherwise resolve to the repo itself) and
# removes nothing on a refusal. Run by hand: bash tests/scripts/test_feature_worktree.sh
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
script=$root/scripts/feature-worktree.sh
fails=0
report() { echo "$1: $2"; [ "$1" = PASS ] || fails=$((fails + 1)); }
for bad in ".." "../.." "a/b" "" ".hidden" "x y"; do
  before=$(ls -A "$root/.claude" | sort | cksum)
  rc=0; "$script" --remove "$bad" >/dev/null 2>&1 || rc=$?
  after=$(ls -A "$root/.claude" | sort | cksum)
  if [ "$rc" -eq 64 ] && [ "$before" = "$after" ]; then
    report PASS "refuses id '$bad' with exit 64 and removes nothing"
  else
    report FAIL "id '$bad': exit $rc, .claude changed: $([ "$before" = "$after" ] && echo no || echo yes)"
  fi
done
[ "$fails" -eq 0 ]
