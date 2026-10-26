#!/usr/bin/env bash
# One git worktree per feature-lane build, made usable without a fresh
# install: .venv, .env and local/ are symlinked from the main checkout and
# apps/web/node_modules is cloned (all gitignored or excluded, so none can
# enter the diff). local/ is shared on purpose: the gate lock and the
# feature's brief and outputs live there. Prints the worktree path.
#
#   scripts/feature-worktree.sh <id>          create .claude/worktrees/<id> on feat/<id> from origin/main
#   scripts/feature-worktree.sh --remove <id> remove the worktree and the local branch
set -euo pipefail

root=$(git rev-parse --show-toplevel)
remove=0
if [[ "${1:-}" == "--remove" ]]; then remove=1; shift; fi
id="${1:-}"
# The id becomes a path component: anything but a plain name is refused, so
# ".." or "a/b" can never resolve outside .claude/worktrees/.
[[ "$id" =~ ^[A-Za-z0-9_-][A-Za-z0-9._-]*$ ]] || { echo "usage: $0 [--remove] <id>  (id: letters, digits, . _ -)" >&2; exit 64; }
path="$root/.claude/worktrees/$id"
branch="feat/$id"

if (( remove )); then
  git -C "$root" worktree remove --force "$path"
  git -C "$root" branch -D "$branch" >/dev/null 2>&1 || true
  echo "removed $path"
  exit 0
fi

git -C "$root" fetch -q origin main
mkdir -p "$root/.claude/worktrees"
git -C "$root" worktree add -q -b "$branch" "$path" origin/main
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
