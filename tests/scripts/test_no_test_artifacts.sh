#!/usr/bin/env bash
# Proves the `no-test-artifacts` pre-commit hook: a staged screenshot, trace,
# recording or archive (any case) fails it; text and source files, and names
# that only contain an extension mid-path, pass. pre-commit is not required:
# the hook's `files:` (and any `exclude:`) regex is read from
# .pre-commit-config.yaml and applied as pre-commit applies it (Python
# re.search over each staged path; `language: fail` fails on any match),
# against the paths staged in a temp repo. Run by hand:
#   bash tests/scripts/test_no_test_artifacts.sh
set -uo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
config=$root/.pre-commit-config.yaml
work=$(mktemp -d "${TMPDIR:-/tmp}/no-artifacts-test.XXXXXX")
. "$root/tests/scripts/lib.sh"
trap 'rm -rf "$work"' EXIT

block=$(awk '/- id: no-test-artifacts$/ {on=1; print; next} on && /- id:/ {exit} on {print}' "$config")
regex=$(printf '%s\n' "$block" | sed -n 's/^[[:space:]]*files:[[:space:]]*//p' | head -1)
exclude=$(printf '%s\n' "$block" | sed -n 's/^[[:space:]]*exclude:[[:space:]]*//p' | head -1)
language=$(printf '%s\n' "$block" | sed -n 's/^[[:space:]]*language:[[:space:]]*//p' | head -1)
# A YAML-quoted scalar: drop the outer quotes.
strip() { local v=$1; v=${v#\'}; v=${v%\'}; v=${v#\"}; v=${v%\"}; printf '%s' "$v"; }
regex=$(strip "$regex"); exclude=$(strip "$exclude")
if [ -z "$regex" ] || [ "$language" != fail ]; then
  report FAIL "could not read the hook's files regex / language: fail from $config"
  exit 1
fi

repo=$work/repo
git init -q "$repo"

# Exit 1 when the hook would fail on what is staged, 0 otherwise.
hook() {
  git -C "$repo" -c core.quotepath=false diff --cached --name-only --diff-filter=ACMR \
    | HOOK_FILES="$regex" HOOK_EXCLUDE="$exclude" python3 -I -c '
import os, re, sys
inc = re.compile(os.environ["HOOK_FILES"])
exc = os.environ["HOOK_EXCLUDE"]
exc = re.compile(exc) if exc else None
hit = [p for p in sys.stdin.read().splitlines()
       if inc.search(p) and not (exc and exc.search(p))]
sys.exit(1 if hit else 0)'
}

stage_only() { # $1 = path; leaves exactly that file staged
  git -C "$repo" rm -rq --cached . > /dev/null 2>&1 || true
  mkdir -p "$repo/$(dirname "$1")"
  printf 'x' > "$repo/$1"
  git -C "$repo" add -- "$1"
}

blocked() { # $1 = path, $2 = label
  stage_only "$1"
  hook && report FAIL "$2 ($1) passes the hook, expected a failure" \
       || report PASS "$2 ($1)"
}
allowed() {
  stage_only "$1"
  hook && report PASS "$2 ($1)" \
       || report FAIL "$2 ($1) fails the hook, expected a pass"
}

# The extension's case does not matter
for f in e2e/shot.PNG e2e/photo.Jpg e2e/run.MP4 e2e/clip.WebM e2e/a.JPEG e2e/b.GIF e2e/c.WEBP e2e/trace.ZIP e2e/net.HAR; do
  blocked "$f" "an upper- or mixed-case artifact extension fails the hook"
done

# Other recording and photo formats
for ext in mov heic avif mkv; do
  blocked "apps/web/test-results/rec.$ext" "a .$ext fails the hook"
done
# Distinct names: on a case-insensitive filesystem rec.MOV would overwrite
# rec.mov and stage nothing.
for ext in MOV HEIC Avif MKV; do
  blocked "apps/web/test-results/upper/recording-upper.$ext" "a .$ext in any case fails the hook"
done

# The original list, at depth and at the root
for ext in png jpg jpeg gif webp webm mp4 zip har; do
  blocked "apps/web/test-results/shot.$ext" "a .$ext fails the hook"
done
blocked "screenshot.png" "a .png at the repo root fails the hook"
blocked "dir with space/shot.png" "a .png under a path with a space fails the hook"

for f in apps/web/public/logo.svg docs/notes.md apps/web/app/page.ts x.png.txt docs/png-notes.md apps/web/zipper.ts e2e/trace.har.json; do
  allowed "$f" "a non-artifact path passes the hook"
done

[ "$fails" -eq 0 ] || { echo "$fails failure(s)"; exit 1; }
echo "all passed"
