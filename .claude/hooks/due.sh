#!/usr/bin/env bash
# UserPromptSubmit hook: before the controller answers, say what the day owes
# (the morning digest, the Friday retro), read from local/routine-marker.json
# and the clock, so the rhythm rests on a file instead of the model's memory of
# it. Prints nothing when nothing is due; never blocks the prompt; exits 0 on
# any failure. `due.sh mark digest|retro` records one as done — the skill
# morning-digest calls it, and until it does the reminder repeats.
# DUE_TODAY (YYYY-MM-DD) overrides the clock for tests.
set -u
root=${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}
marker="$root/local/routine-marker.json"
# No local/ at all is a fresh clone: nothing to run, stay silent. local/ without
# the marker is a configured machine that lost it: silence would read as
# "nothing due", so say so.
if [ ! -f "$marker" ]; then
  [ -d "$root/local" ] && echo "[due] MARKER MISSING: local/routine-marker.json — the daily rhythm (digest, retro) is off until it is restored."
  exit 0
fi

if [ -n "${DUE_TODAY:-}" ]; then
  today=$DUE_TODAY
  dow=$(python3 -c "import datetime,sys;print(datetime.date.fromisoformat(sys.argv[1]).isoweekday())" "$today")
  week=$(python3 -c "import datetime,sys;y,w,_=datetime.date.fromisoformat(sys.argv[1]).isocalendar();print(f'{y}-W{w:02d}')" "$today")
else
  today=$(date +%F) dow=$(date +%u) week=$(date +%G-W%V)
fi

if [ "${1:-}" = mark ]; then
  case "${2:-}" in
    digest) key=last_digest_date val=$today ;;
    retro) key=last_retro_week val=$week ;;
    *) echo "usage: due.sh mark digest|retro" >&2; exit 64 ;;
  esac
  tmp=$(mktemp) && jq --arg k "$key" --arg v "$val" '.[$k] = $v' "$marker" > "$tmp" && mv "$tmp" "$marker"
  exit 0
fi

prompt=$(jq -r '.prompt // empty' 2>/dev/null || true)
last_digest=$(jq -r '.last_digest_date // ""' "$marker")
last_retro=$(jq -r '.last_retro_week // ""' "$marker")
lines=()

if [ "$last_digest" != "$today" ]; then
  # gh is the only network call, made once a day at most; perl's alarm bounds it
  # because macOS ships no timeout(1).
  prs=$(cd "$root" && perl -e 'alarm 8; exec @ARGV' gh pr list --state open --limit 100 --json headRefName \
    -q '[.[].headRefName] | "\(map(select(startswith("routine/"))) | length) routine, \(map(select(startswith("journey/"))) | length) journey, \(map(select(startswith("feat/"))) | length) feature"' 2>/dev/null) \
    || prs="unknown (gh failed)"
  explorer=$(cd "$root/local/explorer" 2>/dev/null && ls -1 [0-9]*.md 2>/dev/null | awk -v d="$last_digest" 'substr($0,1,10) > d' | tr '\n' ' ')
  briefs=$(jq -r '[.features[]? | select(.state == "brief")] | length' "$root/local/features.json" 2>/dev/null || echo 0)
  lines+=("DIGEST DUE (skill morning-digest; last digest: ${last_digest:-never}). Open PRs: $prs. Briefs waiting: $briefs. New explorer notes: ${explorer:-none}. Read every routine run newer than the marker's last_reported_run / journeys_last_reported_run before anything else; finish with \`.claude/hooks/due.sh mark digest\`.")
fi

if [ "$dow" -ge 5 ] && [ "$last_retro" != "$week" ]; then
  wf="local/retro/$week.md"
  tally=$(grep -oE '^- [0-9]{4}-[0-9]{2}-[0-9]{2} \[[a-z-]+\]' "$root/$wf" 2>/dev/null \
    | sed -E 's/.*\[([a-z-]+)\]/\1/' | sort | uniq -c | sort -rn \
    | awk '{printf "%s%s %d%s", (NR>1?", ":""), $2, $1, ($1>=2?" (recurring)":"")}')
  lines+=("RETRO DUE for $week (skill morning-digest, Friday). Week file $wf tally: ${tally:-empty}. Run scripts/week_transcript.py first so the tally includes what the context forgot; finish with \`.claude/hooks/due.sh mark retro\`.")
fi

if [ ${#lines[@]} -eq 0 ]; then
  case "$prompt" in BAU|bau|BAU*) echo "[due] BAU: nothing is due (digest done $last_digest)." ;; esac
  exit 0
fi
for l in "${lines[@]}"; do echo "[due] $l"; done
exit 0
