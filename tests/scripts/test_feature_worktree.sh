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

# Everything below runs in a temp clone of a temp bare origin, with the script
# copied in and committed, so nothing touches this repo's .claude/worktrees/.
work=$(mktemp -d "${TMPDIR:-/tmp}/feature-worktree-test.XXXXXX")
work=$(cd "$work" && pwd -P)
trap 'rm -rf "$work"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com

seed=$work/seed
git init -q -b main "$seed"
mkdir -p "$seed/apps/web" "$seed/scripts"
cp "$script" "$seed/scripts/feature-worktree.sh"
echo '{"name":"web","private":true}' > "$seed/apps/web/package.json"
printf 'node_modules/\n.venv/\n.env\nlocal/\n.claude/worktrees/\n' > "$seed/.gitignore"
echo hello > "$seed/README"
git -C "$seed" add -A && git -C "$seed" commit -qm one
git clone -q --bare "$seed" "$work/origin.git"
main=$work/main
git clone -q "$work/origin.git" "$main"
mkdir -p "$main/.venv/bin" "$main/local" "$main/apps/web/node_modules/pkg"
echo 'X=fake' > "$main/.env"
echo 'module.exports=1' > "$main/apps/web/node_modules/pkg/index.js"
# Off macOS the script's node_modules fallback is an install, which this test cannot run.
[ "$(uname)" = Darwin ] || rm -rf "$main/apps/web/node_modules"

wt() { echo "$main/.claude/worktrees/$1"; }
fw() { (cd "$main" && bash scripts/feature-worktree.sh "$@"); }
has_branch() { git -C "$main" show-ref --verify -q "refs/heads/feat/$1"; }
create() { fw "$1" >/dev/null 2>&1 && [ -d "$(wt "$1")" ]; }

for bad in '-rf' '-x'; do
  before=$(cd "$work" && find . -path ./main/.git -prune -o -print | LC_ALL=C sort | cksum)
  rc=0; fw "$bad" >/dev/null 2>&1 || rc=$?
  after=$(cd "$work" && find . -path ./main/.git -prune -o -print | LC_ALL=C sort | cksum)
  [ "$rc" -eq 64 ] && [ "$before" = "$after" ] && ! has_branch "$bad" \
    && report PASS "an id starting with '-' ('$bad') exits 64 and creates nothing" \
    || report FAIL "id '$bad': exit $rc, tree changed: $([ "$before" = "$after" ] && echo no || echo yes)"
  rc=0; fw --remove "$bad" >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 64 ] && report PASS "--remove with an id starting with '-' ('$bad') exits 64" || report FAIL "--remove '$bad': exit $rc"
done

if create up; then
  rc=0; git -C "$main" rev-parse --abbrev-ref 'feat/up@{upstream}' >/dev/null 2>&1 || rc=$?
  [ "$rc" -ne 0 ] && report PASS "the created branch has no upstream" || report FAIL "feat/up has an upstream: $(git -C "$main" rev-parse --abbrev-ref 'feat/up@{upstream}')"
else
  report FAIL "could not create worktree 'up'"
fi

# W2: uncommitted changes block a plain --remove; --force removes.
if create dirty; then
  echo change >> "$(wt dirty)/README"
  rc=0; out=$(fw --remove dirty 2>&1) || rc=$?
  [ "$rc" -ne 0 ] && [ -d "$(wt dirty)" ] && has_branch dirty \
    && report PASS "--remove refuses a worktree with uncommitted changes and leaves it and its branch" \
    || report FAIL "--remove with uncommitted changes: exit $rc, dir $([ -d "$(wt dirty)" ] && echo kept || echo gone)"
  case "$out" in *README*) report PASS "the refusal names the uncommitted change" ;; *) report FAIL "refusal does not name README: '$out'" ;; esac
  rc=0; fw --remove --force dirty >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 0 ] && [ ! -e "$(wt dirty)" ] && ! has_branch dirty \
    && report PASS "--remove --force removes a worktree with uncommitted changes and its branch" \
    || report FAIL "--remove --force with uncommitted changes: exit $rc"
else
  report FAIL "could not create worktree 'dirty'"
fi

# W3: commits on no remote branch block a plain --remove; --force removes.
if create ahead; then
  echo more >> "$(wt ahead)/README" && git -C "$(wt ahead)" commit -qam ahead
  rc=0; fw --remove ahead >/dev/null 2>&1 || rc=$?
  [ "$rc" -ne 0 ] && [ -d "$(wt ahead)" ] && has_branch ahead \
    && report PASS "--remove refuses a branch with unpushed commits and leaves it in place" \
    || report FAIL "--remove with unpushed commits: exit $rc"
  rc=0; fw --remove --force ahead >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 0 ] && [ ! -e "$(wt ahead)" ] && ! has_branch ahead \
    && report PASS "--remove --force removes a branch with unpushed commits" \
    || report FAIL "--remove --force with unpushed commits: exit $rc"
else
  report FAIL "could not create worktree 'ahead'"
fi

# Commits that are on a remote branch are not unpushed.
if create pushed; then
  echo more >> "$(wt pushed)/README" && git -C "$(wt pushed)" commit -qam pushed
  git -C "$(wt pushed)" push -q origin feat/pushed
  rc=0; fw --remove pushed >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 0 ] && [ ! -e "$(wt pushed)" ] && ! has_branch pushed \
    && report PASS "--remove removes a branch whose commits are on a remote branch" \
    || report FAIL "--remove with pushed commits: exit $rc"
else
  report FAIL "could not create worktree 'pushed'"
fi

# W6: a clean worktree with nothing unpushed is removed.
if create clean; then
  rc=0; fw --remove clean >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 0 ] && [ ! -e "$(wt clean)" ] && ! has_branch clean \
    && report PASS "--remove removes a clean worktree with nothing unpushed, exit 0" \
    || report FAIL "--remove clean: exit $rc"
else
  report FAIL "could not create worktree 'clean'"
fi

# W7: a branch left behind with no registered worktree is cleared by --force.
if create orphan; then
  rm -rf "$(wt orphan)" && git -C "$main" worktree prune
  rc=0; fw --remove --force orphan >/dev/null 2>&1 || rc=$?
  ok=1; [ "$rc" -eq 0 ] && ! has_branch orphan || ok=0
  rc2=0; fw orphan >/dev/null 2>&1 || rc2=$?
  [ "$ok" -eq 1 ] && [ "$rc2" -eq 0 ] && [ -d "$(wt orphan)" ] \
    && report PASS "--remove --force deletes a branch with no registered worktree, exit 0, and <id> can be made again" \
    || report FAIL "--remove --force on an orphan branch: exit $rc, branch $(has_branch orphan && echo kept || echo gone), recreate exit $rc2"
else
  report FAIL "could not create worktree 'orphan'"
fi

# W5: run from inside another worktree, both forms act on the main checkout.
if create other && create inner; then
  o=$(wt other)
  rc=0; out=$(cd "$o" && bash scripts/feature-worktree.sh fromwt 2>&1) || rc=$?
  [ "$rc" -eq 0 ] && [ -d "$(wt fromwt)" ] && [ ! -e "$o/.claude/worktrees/fromwt" ] \
    && report PASS "run inside another worktree, <id> creates under the main checkout" \
    || report FAIL "create from a worktree: exit $rc, main $([ -d "$(wt fromwt)" ] && echo yes || echo no), nested $([ -e "$o/.claude/worktrees/fromwt" ] && echo yes || echo no)"
  case "$out" in *"$(wt fromwt)"*) report PASS "run inside another worktree, the printed path is the main checkout's" ;; *) report FAIL "printed path: '$out'" ;; esac
  rc=0; (cd "$o" && bash scripts/feature-worktree.sh --remove inner >/dev/null 2>&1) || rc=$?
  [ "$rc" -eq 0 ] && [ ! -e "$(wt inner)" ] && ! has_branch inner \
    && report PASS "run inside another worktree, --remove <id> removes the main checkout's worktree" \
    || report FAIL "remove from a worktree: exit $rc, main's inner $([ -e "$(wt inner)" ] && echo kept || echo gone)"
  [ ! -e "$o/.claude/worktrees" ] && report PASS "nothing is made under the other worktree's .claude/worktrees" \
    || report FAIL "the other worktree has $(ls -A "$o/.claude/worktrees")"
else
  report FAIL "could not create worktrees 'other' and 'inner'"
fi

[ "$fails" -eq 0 ] && echo "all passed" || echo "$fails failed"
[ "$fails" -eq 0 ]
