#!/usr/bin/env bash
# Proves scripts/feature-worktree.sh refuses an id that could leave
# .claude/worktrees/ ("" is the folder itself, ".." resolves to .claude/,
# "../.." to the repo) and creates or removes nothing on a refusal (the temp clone's whole tree is compared before
# and after). Run by hand: bash tests/scripts/test_feature_worktree.sh
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
script=$root/scripts/feature-worktree.sh
fails=0
report() { echo "$1: $2"; [ "$1" = PASS ] || fails=$((fails + 1)); }
# Everything runs in a temp clone of a temp bare origin, with the script
# copied in and committed, so nothing touches this repo, and no other session's
# writes under this repo's .claude/ can make a case fail.
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
# A line-start match, not grep in a pipe: under pipefail an early grep exit can
# fail the writer and flip a negated check.
says_removed() { case $'\n'"$1" in *$'\n''removed '*) return 0 ;; esac; return 1; }

# Something for a wrongly accepted id to destroy: the folders "a/b", ".hidden"
# and "x y" would name, a sentinel beside them, and --force, the only path
# that deletes. ("." and ".." segments stay exit-code-only: rm refuses them.)
mkdir -p "$main/.claude/worktrees/a/b" "$main/.claude/worktrees/.hidden" "$main/.claude/worktrees/x y"
touch "$main/.claude/worktrees/keep" "$main/.claude/keep"
for bad in ".." "../.." "a/b" "" ".hidden" "x y"; do
  for mode in "--remove --force" "create"; do
    before=$(cd "$work" && find . -path ./main/.git -prune -o -print | LC_ALL=C sort | cksum)
    rc=0
    if [ "$mode" = create ]; then fw "$bad" >/dev/null 2>&1 || rc=$?; else fw --remove --force "$bad" >/dev/null 2>&1 || rc=$?; fi
    after=$(cd "$work" && find . -path ./main/.git -prune -o -print | LC_ALL=C sort | cksum)
    if [ "$rc" -eq 64 ] && [ "$before" = "$after" ]; then
      report PASS "refuses id '$bad' ($mode) with exit 64 and changes nothing"
    else
      report FAIL "id '$bad' ($mode): exit $rc, tree changed: $([ "$before" = "$after" ] && echo no || echo yes)"
    fi
  done
done
rm -rf "$main/.claude/worktrees/a" "$main/.claude/worktrees/.hidden" "$main/.claude/worktrees/x y" \
  "$main/.claude/worktrees/keep" "$main/.claude/keep"

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

# Uncommitted changes block a plain --remove; --force removes.
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

# Commits on no remote branch block a plain --remove; --force removes.
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

# A clean worktree with nothing unpushed is removed.
if create clean; then
  rc=0; fw --remove clean >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 0 ] && [ ! -e "$(wt clean)" ] && ! has_branch clean \
    && report PASS "--remove removes a clean worktree with nothing unpushed, exit 0" \
    || report FAIL "--remove clean: exit $rc"
else
  report FAIL "could not create worktree 'clean'"
fi

# A branch left behind with no registered worktree is cleared by --force.
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

# A hand-deleted worktree whose branch has nothing unpushed needs no --force;
# the directory is already gone, so nothing uncommitted can be lost.
if create gone; then
  rm -rf "$(wt gone)" && git -C "$main" worktree prune
  rc=0; fw --remove gone >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 0 ] && ! has_branch gone \
    && report PASS "--remove deletes a branch whose worktree was deleted by hand, nothing unpushed, exit 0" \
    || report FAIL "--remove on a hand-deleted worktree: exit $rc, branch $(has_branch gone && echo kept || echo gone)"
else
  report FAIL "could not create worktree 'gone'"
fi

# With the directory gone, unpushed commits still block a plain --remove;
# the branch is then their only copy.
if create goneahead; then
  echo more >> "$(wt goneahead)/README" && git -C "$(wt goneahead)" commit -qam goneahead
  rm -rf "$(wt goneahead)" && git -C "$main" worktree prune
  rc=0; out=$(fw --remove goneahead 2>&1) || rc=$?
  [ "$rc" -ne 0 ] && has_branch goneahead && ! says_removed "$out" \
    && report PASS "--remove refuses a branch with unpushed commits whose worktree was deleted by hand, and keeps it" \
    || report FAIL "--remove on a hand-deleted worktree with unpushed commits: exit $rc, branch $(has_branch goneahead && echo kept || echo gone), out '$out'"
else
  report FAIL "could not create worktree 'goneahead'"
fi

# A directory at the worktree path that git does not know as a worktree
# (a half-made add) is cleared by --force, and "removed" means both are gone.
git -C "$main" branch -q feat/half origin/main
mkdir -p "$(wt half)" && echo stray > "$(wt half)/file"
rc=0; out=$(fw --remove --force half 2>&1) || rc=$?
[ "$rc" -eq 0 ] && [ ! -e "$(wt half)" ] && ! has_branch half \
  && report PASS "--remove --force deletes an unregistered directory at the worktree path and its branch, exit 0" \
  || report FAIL "--remove --force on an unregistered directory: exit $rc, dir $([ -e "$(wt half)" ] && echo kept || echo gone), branch $(has_branch half && echo kept || echo gone)"
says_removed "$out" && report PASS "--remove --force on an unregistered directory prints 'removed'" \
  || report FAIL "--remove --force on an unregistered directory does not print 'removed': '$out'"

# The same after a real worktree was deleted, pruned and its path remade by hand.
if create remade; then
  rm -rf "$(wt remade)" && git -C "$main" worktree prune
  mkdir -p "$(wt remade)" && echo stray > "$(wt remade)/file"
  rc=0; out=$(fw --remove --force remade 2>&1) || rc=$?
  [ "$rc" -eq 0 ] && [ ! -e "$(wt remade)" ] && ! has_branch remade && says_removed "$out" \
    && report PASS "--remove --force deletes a remade unregistered directory and its branch, prints 'removed', exit 0" \
    || report FAIL "--remove --force on a remade directory: exit $rc, dir $([ -e "$(wt remade)" ] && echo kept || echo gone), branch $(has_branch remade && echo kept || echo gone), out '$out'"
else
  report FAIL "could not create worktree 'remade'"
fi

# Without --force an unregistered directory is never deleted; it may hold
# the only copy of work that git does not track.
git -C "$main" branch -q feat/halfkeep origin/main
mkdir -p "$(wt halfkeep)" && echo stray > "$(wt halfkeep)/file"
rc=0; out=$(fw --remove halfkeep 2>&1) || rc=$?
[ "$rc" -ne 0 ] && [ -f "$(wt halfkeep)/file" ] && ! says_removed "$out" \
  && report PASS "--remove without --force keeps an unregistered directory, exits non-zero and does not claim 'removed'" \
  || report FAIL "--remove on an unregistered directory: exit $rc, dir $([ -e "$(wt halfkeep)" ] && echo kept || echo gone), out '$out'"

# Run from inside another worktree, both forms act on the main checkout.
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
