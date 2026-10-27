#!/usr/bin/env bash
# UserPromptSubmit hook: before the controller answers, say what the day owes
# (the morning digest, the Friday retro, the weekly explorer's findings), read
# from local/routine-marker.json and the clock, so the rhythm rests on a file
# instead of the model's memory of it. From Friday on it also starts the
# week's explorer run (scripts/explorer.sh) in the background, once per ISO
# week. Prints nothing when nothing is due; never blocks the prompt; exits 0 on
# any failure. `due.sh mark digest|retro|explorer` records one as done — the
# skill morning-digest calls it, and until it does the reminder repeats.
# DUE_TODAY (YYYY-MM-DD) overrides the clock for tests.
set -u
# The explorer's own headless session runs in this repo too: it gets no
# reminders and must never start another explorer.
[ -n "${HAX_EXPLORER_RUN:-}" ] && exit 0
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
    explorer) key=explorer_reported_week val=$week ;;
    *) echo "usage: due.sh mark digest|retro|explorer" >&2; exit 64 ;;
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

# The explorer: launched on the first prompt from Friday on, so it explores
# while the morning's reviews happen; reported until its findings are triaged.
runner="$root/scripts/explorer.sh"
if [ "$dow" -ge 5 ] && [ -x "$runner" ]; then
  if [ "$(jq -r '.last_explorer_week // ""' "$marker")" != "$week" ]; then
    if verdict=$(cd "$root" && DUE_TODAY=$today perl -e 'alarm 10; exec @ARGV' "$runner" --check 2>&1); then
      mkdir -p "$root/local/explorer"
      (cd "$root" && DUE_TODAY=$today nohup "$runner" </dev/null >>"$root/local/explorer/runner.log" 2>&1 &)
      tmp=$(mktemp) && jq --arg v "$week" '.last_explorer_week = $v' "$marker" > "$tmp" && mv "$tmp" "$marker"
      lines+=("EXPLORER LAUNCHED for $week: persona ${verdict#ok }, main on :3002/:8002 with the real model, about an hour. Notes land in local/explorer/; the hook reports when it ends.")
    else
      lines+=("EXPLORER WAITING for $week: ${verdict:-the check failed}. The first prompt after that is fixed launches it.")
    fi
  elif [ "$(jq -r '.explorer_reported_week // ""' "$marker")" != "$week" ]; then
    st="$root/local/explorer/.status.json"
    if [ "$(jq -r '.week // ""' "$st" 2>/dev/null)" = "$week" ]; then
      case "$(jq -r '.state' "$st")" in
        done) lines+=("EXPLORER DONE for $week: $(jq -r '"persona \(.persona), notes \(.notes)"' "$st"). Triage per skill product-explorer (After the run); finish with \`.claude/hooks/due.sh mark explorer\`.") ;;
        failed) lines+=("EXPLORER FAILED for $week: $(jq -r '"\(.reason). Logs: \(.logs)"' "$st"). A week-file line [routine-abandon]; rerun by hand or let it go; finish with \`.claude/hooks/due.sh mark explorer\`.") ;;
      esac
    fi
  fi
fi

# The day's state, independent of how a question about it is worded: every
# prompt carries a pointer to its source, and the day's first prompt carries the
# state itself (scripts/state.sh, which also prints the ordered next list), so
# an answer about what is open or what comes next starts from the files, not
# from recall.
full=""
if [ -x "$root/scripts/state.sh" ] && [ "$(jq -r '.last_state_date // ""' "$marker")" != "$today" ]; then
  full=$(cd "$root" && DUE_TODAY=$today perl -e 'alarm 12; exec @ARGV' "$root/scripts/state.sh" 2>/dev/null) || full=""
  tmp=$(mktemp) && jq --arg v "$today" '.last_state_date = $v' "$marker" > "$tmp" && mv "$tmp" "$marker"
fi

if [ ${#lines[@]} -eq 0 ]; then
  case "$prompt" in BAU|bau|BAU*) echo "[due] BAU: nothing is due (digest done $last_digest)." ;; esac
fi
for l in ${lines[@]+"${lines[@]}"}; do echo "[due] $l"; done
echo "[state] For the day's state, what is open or what comes next: \`scripts/state.sh\` prints it live, with the ordered next list from the backlog's START HERE. Read it before answering; never answer from recall."
[ -n "$full" ] && printf '%s\n' "$full"
exit 0
