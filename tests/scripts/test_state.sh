#!/usr/bin/env bash
# Proves scripts/state.sh: the live state is printed from its sources (git,
# the open PRs, the feature ledger, the nightly queue, the marker, the week's
# retro file, the explorer's status), and the ordered next list is printed
# from the backlog's "### Next" section, then every open item from its
# "## Open items" section; a missing source is named, never
# guessed. gh is stubbed, the clock pinned with DUE_TODAY. Run by hand:
#   bash tests/scripts/test_state.sh
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
script=$root/scripts/state.sh
work=$(mktemp -d "${TMPDIR:-/tmp}/state-test.XXXXXX")
. "$root/tests/scripts/lib.sh"
trap 'rm -rf "$work"' EXIT

has() { # $1 = name, $2 = needle
  case "$out" in *"$2"*) report PASS "$1" ;; *) report FAIL "$1: no '$2' in: $out" ;; esac
}

p=$work/proj
mkdir -p "$work/bin" "$p/local/retro" "$p/local/explorer"
# The gh stub answers `pr list` with canned JSON and applies a `-q` expression
# with jq, as real gh does, so state.sh's own counting expression is what the
# assertions exercise; anything else it is asked fails.
cat > "$work/bin/gh" <<'GH'
#!/usr/bin/env bash
[ "${1:-} ${2:-}" = "pr list" ] || { echo "gh stub: unexpected: $*" >&2; exit 2; }
shift 2
q=""
while [ $# -gt 0 ]; do
  case $1 in -q | --jq) q=$2; shift 2 ;; *) shift ;; esac
done
json='[{"headRefName":"routine/m5-1"},{"headRefName":"routine/m5-2"},{"headRefName":"journey/sweep"},{"headRefName":"feat/about-you"},{"headRefName":"fix/other"}]'
if [ -n "$q" ]; then jq -r "$q" <<<"$json"; else echo "$json"; fi
GH
chmod +x "$work/bin/gh"
git -C "$p" init -q -b main
git -C "$p" -c user.email=t@t -c user.name=t commit -q --allow-empty -m "first: the start"
git -C "$p" -c user.email=t@t -c user.name=t commit -q --allow-empty -m "second: the latest"
echo '{"features": [{"id": "pilot-76", "state": "merged", "title": "A failed reply"}, {"id": "server-turn", "state": "brief", "title": "A reply finishes"}]}' > "$p/local/features.json"
printf -- '- id: m5-1   branch: routine/m5-1\n  task: one\n- id: m5-2   branch: routine/m5-2\n  task: two\n' > "$p/local/routine-queue.md"
echo '{"last_digest_date": "2026-10-27", "last_retro_week": "2026-W43"}' > "$p/local/routine-marker.json"
printf -- '- 2026-10-27 [forgot] a\n- 2026-10-27 [forgot] b\n- 2026-10-27 [flake] c\n' > "$p/local/retro/2026-W44.md"
echo '{"week": "2026-W44", "state": "done", "persona": "busy", "notes": "local/explorer/x.md"}' > "$p/local/explorer/.status.json"
cat > "$p/local/DEV_BACKLOG.local.md" <<'EOF'
# Dev backlog

## START HERE

### Next (the maintainer's order)
1. server-turn: approve the card.
2. About you: write the brief.

### Things a new session would otherwise rediscover
- not part of the list

## Open items

### Main lane
- **80** `[H:auth]` the login hang

### Nightly (`[R]`)
- **5** `[R]` static ingest errors

## Closed by the audit
- not open
EOF

run() { PATH="$work/bin:$PATH" CLAUDE_PROJECT_DIR="$p" DUE_TODAY=2026-10-27 "$script" "$@" 2>&1 || true; }

out=$(run)
has "main's head is named" "main at $(git -C "$p" rev-parse --short HEAD)"
has "the latest commit's subject is shown" "second: the latest"
has "the open PRs are counted by branch prefix from gh's JSON" "open PRs: 2 routine, 1 journey, 1 feature, 5 in all"
has "each feature is listed with its state" "server-turn: brief"
has "the nightly queue is counted with its ids" "2 items (m5-1, m5-2)"
has "the last digest is named" "digest 2026-10-27"
has "the week's tally flags a recurring category" "forgot 2 (recurring)"
has "the explorer's state is named" "explorer 2026-W44: done"
has "the next list is printed" "1. server-turn: approve the card."
has "the next list's second item is printed" "2. About you: write the brief."
case "$out" in *"not part of the list"*) report FAIL "the next list ran past its section" ;; *) report PASS "the next list stops at its section's end" ;; esac
has "every open item is printed, by lane" "### Main lane"
has "an open main-lane item is printed" "**80** \`[H:auth]\` the login hang"
has "an open nightly item is printed" "**5** \`[R]\` static ingest errors"
case "$out" in *"not open"*) report FAIL "the open items ran past their section" ;; *) report PASS "the open items stop at their section's end" ;; esac

rm "$p/local/features.json"
out=$(run)
has "a missing source is named" "features.json missing"

sed -i.bak '/^## Open items/,$d' "$p/local/DEV_BACKLOG.local.md"
out=$(run)
has "a missing open-items section is named" "no '## Open items' section"

out=$(run --next)
case "$out" in *"1. server-turn"*) case "$out" in *"main at"*) report FAIL "--next printed the state" ;; *) report PASS "--next prints only the list" ;; esac ;; *) report FAIL "--next: '$out'" ;; esac

finish
