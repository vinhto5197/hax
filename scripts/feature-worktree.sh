#!/usr/bin/env bash
# One git worktree per feature-lane build, made usable without a fresh
# install: .venv, .env and local/ are symlinked from the main checkout and
# apps/web/node_modules is cloned (all gitignored or excluded, so none can
# enter the diff). local/ is shared on purpose: the gate lock and the
# feature's brief and outputs live there. Prints the worktree path.
#
#   scripts/feature-worktree.sh <id>                    create .claude/worktrees/<id> on feat/<id> from origin/main
#   scripts/feature-worktree.sh --remove [--force] <id> remove the worktree and the local branch;
#                                                       without --force, refuses uncommitted changes or unpushed commits;
#                                                       with --force, also deletes a directory that is not a registered worktree
set -euo pipefail

# The main checkout, never the current worktree: run from inside one,
# --show-toplevel would nest new worktrees (and the symlink sources) there.
root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
remove=0
force=0
if [[ "${1:-}" == "--remove" ]]; then
  remove=1; shift
  if [[ "${1:-}" == "--force" ]]; then force=1; shift; fi
fi
id="${1:-}"
# The id becomes a path component and a git argument: anything but a plain
# name is refused, so ".." or "a/b" can never resolve outside
# .claude/worktrees/ and a leading "-" can never be read as an option.
[[ "$id" =~ ^[A-Za-z0-9_][A-Za-z0-9._-]*$ ]] || { echo "usage: $0 [--remove [--force]] <id>  (id: letters, digits, . _ -; not starting with . or -)" >&2; exit 64; }
path="$root/.claude/worktrees/$id"
branch="feat/$id"

if (( remove )); then
  has_branch() { git -C "$root" show-ref --verify -q "refs/heads/$branch"; }
  registered=0
  git -C "$root" worktree list --porcelain | grep -qxF "worktree $path" && registered=1
  if (( ! force )); then
    # A directory deleted by hand still leaves the branch to clear; only a
    # missing directory AND a missing branch is nothing to remove.
    if [[ -d "$path" ]]; then
      (( registered )) || { echo "refusing to remove $path: not a registered worktree (--force deletes it)" >&2; exit 1; }
      dirty=$(git -C "$path" status --porcelain --untracked-files=all)
      if [[ -n "$dirty" ]]; then
        { echo "refusing to remove $path: uncommitted changes (--force to discard):"; echo "$dirty"; } >&2
        exit 1
      fi
    elif ! has_branch; then
      echo "no worktree at $path" >&2; exit 1
    fi
    if has_branch; then
      unpushed=$(git -C "$root" log --oneline "refs/heads/$branch" --not --remotes --)
      if [[ -n "$unpushed" ]]; then
        { echo "refusing to remove $branch: commits on no remote branch (--force to discard):"; echo "$unpushed"; } >&2
        exit 1
      fi
    fi
  fi
  # A branch whose worktree is already gone (pruned, or deleted by hand) is
  # still removed: left behind, it would block the next `<id>`.
  if (( registered )); then
    if [[ -d "$path" ]]; then
      git -C "$root" worktree remove --force "$path"
    else
      git -C "$root" worktree prune
    fi
  elif (( force )) && [[ -e "$path" ]]; then
    # Not a worktree (a half-made add): a plain directory, and inside
    # .claude/worktrees/ by the id rule above.
    rm -rf "$path"
  fi
  git -C "$root" branch -D "$branch" >/dev/null 2>&1 || true
  if [[ -e "$path" ]] || has_branch; then
    echo "could not remove $path and $branch" >&2
    exit 1
  fi
  echo "removed $path"
  exit 0
fi

git -C "$root" fetch -q origin main
mkdir -p "$root/.claude/worktrees"
# --no-track: an upstream of origin/main would send a bare `git push` to main.
git -C "$root" worktree add -q --no-track -b "$branch" "$path" origin/main
# The symlinks are files, and .gitignore's directory patterns (local/,
# .venv/) do not match them, so they are excluded in .git/info/exclude,
# which every worktree shares (written once, never duplicated).
exclude=$(git -C "$path" rev-parse --git-path info/exclude)
for link in .venv .env local; do
  if [[ -e "$root/$link" && ! -e "$path/$link" ]]; then
    ln -s "$root/$link" "$path/$link"
    grep -qxF "/$link" "$exclude" 2>/dev/null || echo "/$link" >> "$exclude"
  fi
done
# node_modules cannot be a symlink: Next's bundler refuses one that resolves
# outside the project root. A copy-on-write clone is instant on APFS; anywhere
# else, a real install.
if [[ -d "$root/apps/web/node_modules" && ! -e "$path/apps/web/node_modules" ]]; then
  cp -cR "$root/apps/web/node_modules" "$path/apps/web/node_modules" 2>/dev/null \
    || (cd "$path/apps/web" && npm ci --no-audit --no-fund >/dev/null)
fi
echo "$path"
