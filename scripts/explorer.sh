#!/usr/bin/env bash
# The weekly product explorer: one persona uses main's build of the product on
# an isolated local stack with the real model, and writes what confused it to
# local/explorer/<date>-<persona>.md with screenshots beside it. The due hook
# (.claude/hooks/due.sh) starts it in the background on the first prompt from
# Friday on, once per ISO week; it also runs by hand. Never production, never
# the dev stack's data or ports, and it stops only the processes it started.
#
#   scripts/explorer.sh             run (about an hour; blocks)
#   scripts/explorer.sh --check     print "ok <persona>" and exit 0 if a run can start now, else the reason, exit 1
#   scripts/explorer.sh --persona   print this week's persona
#
# The stack: web :3002, API :8002, database hax_explorer and Redis db 14
# (both emptied by apps/web/e2e/prepare.py --target explorer), one worker for
# both queues, dev MinIO (bucket hax-explorer) and dev Mailpit (inbox :8025,
# so the persona verifies its signup the way a person would). The model and
# embedding keys reach the API and worker from the root .env and nothing else
# does; the explorer agent never sees them.
#
# Knobs: EXPLORER_PERSONA (a persona-*.md name), EXPLORER_TURNS (chat messages
# to hax, default 40), EXPLORER_BUDGET_USD (the agent's spend, default 15),
# EXPLORER_MODEL (default claude-sonnet-5-5: a full run fits the budget), EXPLORER_CHECKOUT (run that
# checkout instead of a fresh worktree of origin/main; it is left in place),
# DUE_TODAY (YYYY-MM-DD, the clock for tests).
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

root=${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
dir="$root/local/explorer"
lock="$dir/.running"
status="$dir/.status.json"
personas_dir="$root/.claude/skills/product-explorer"
WEB=3002 API=8002 MAILPIT_UI=8025
WALL_SECONDS=3600

today=${DUE_TODAY:-$(date +%F)}
read -r week week_num < <(python3 -c "import datetime,sys;y,w,_=datetime.date.fromisoformat(sys.argv[1]).isocalendar();print(f'{y}-W{w:02d}',w)" "$today")

# The persona rotates by ISO week over the files present, so adding one
# changes the order but never needs state.
pick_persona() {
  if [[ -n "${EXPLORER_PERSONA:-}" ]]; then echo "$EXPLORER_PERSONA"; return; fi
  local files=("$personas_dir"/persona-*.md)
  [[ -e "${files[0]}" ]] || { echo "none"; return; }
  local f=${files[$(( week_num % ${#files[@]} ))]}
  f=${f##*/persona-}; echo "${f%.md}"
}

listening() { nc -z -G 2 localhost "$1" >/dev/null 2>&1 || nc -z -w 2 localhost "$1" >/dev/null 2>&1; }

check() {
  [[ -d "$root/local" ]] || { echo "local/ is missing"; return 1; }
  if [[ -f "$lock" ]] && kill -0 "$(cat "$lock")" 2>/dev/null; then
    echo "already running (pid $(cat "$lock"))"; return 1
  fi
  local persona; persona=$(pick_persona)
  [[ -f "$personas_dir/persona-$persona.md" ]] || { echo "no persona file persona-$persona.md"; return 1; }
  [[ -f "$root/.env" ]] || { echo "no .env at the repo root (the model key comes from it)"; return 1; }
  [[ -x "$root/.venv/bin/python" ]] || { echo "no .venv (run make setup)"; return 1; }
  [[ -d "$root/apps/web/node_modules" ]] || { echo "no apps/web/node_modules (run make sync-web)"; return 1; }
  command -v claude >/dev/null || { echo "the claude CLI is not on PATH"; return 1; }
  local name port name_port
  for name_port in Postgres:5432 Redis:6379 MinIO:9000 Mailpit:1025; do
    name=${name_port%:*} port=${name_port#*:}
    listening "$port" || { echo "$name :$port is unreachable: start Docker and run make infra-up"; return 1; }
  done
  for port in $WEB $API; do
    listening "$port" && { echo "port $port is in use"; return 1; }
  done
  echo "ok $persona"
}

case "${1:-}" in
  --check) check; exit ;;
  --persona) pick_persona; exit 0 ;;
  "") ;;
  *) echo "usage: $0 [--check|--persona]" >&2; exit 64 ;;
esac

verdict=$(check) || { echo "explorer: $verdict" >&2; exit 1; }
persona=${verdict#ok }
turns=${EXPLORER_TURNS:-40}
budget=${EXPLORER_BUDGET_USD:-15}
model=${EXPLORER_MODEL:-claude-sonnet-5-5}
run_id="$today-$persona"
notes="$dir/$run_id.md"
run_dir="$dir/$run_id"
mkdir -p "$run_dir"
started=$(date +%s)

write_status() { # state [reason]
  jq -n --arg week "$week" --arg persona "$persona" --arg state "$1" --arg reason "${2:-}" \
    --arg notes "local/explorer/$run_id.md" --arg logs "local/explorer/$run_id/" \
    --arg started "$(date -r "$started" +%FT%T%z)" --arg updated "$(date +%FT%T%z)" \
    '{week: $week, persona: $persona, state: $state, reason: $reason, notes: $notes, logs: $logs, started: $started, updated: $updated}' \
    > "$status.tmp" && mv "$status.tmp" "$status"
}

pids=()
checkout=""
finish() {
  local code=$?
  for pid in ${pids[@]+"${pids[@]}"}; do kill "$pid" 2>/dev/null || true; done
  # The Playwright MCP server outlives a killed agent; its args name this run's
  # directory, which nothing else on the machine does.
  pkill -f -- "--output-dir $run_dir" 2>/dev/null || true
  if [[ -z "${EXPLORER_CHECKOUT:-}" && -n "$checkout" ]]; then
    "$root/scripts/feature-worktree.sh" --remove explorer >/dev/null 2>&1 || true
  fi
  if (( code != 0 )) && [[ "$(jq -r .state "$status" 2>/dev/null)" == running ]]; then
    write_status failed "the runner stopped with exit $code; see $run_dir/runner.log"
  fi
  rm -f "$lock"
}
trap finish EXIT
trap 'exit 130' INT TERM
echo $$ > "$lock"
write_status running
exec > >(tee -a "$run_dir/runner.log") 2>&1
echo "explorer $run_id: started $(date)"

step() { echo "explorer: $*"; write_status running "$*"; }

if [[ -n "${EXPLORER_CHECKOUT:-}" ]]; then
  checkout=$EXPLORER_CHECKOUT
else
  step "making a worktree of origin/main"
  "$root/scripts/feature-worktree.sh" --remove explorer >/dev/null 2>&1 || true
  checkout=$("$root/scripts/feature-worktree.sh" explorer | tail -1)
fi
cd "$checkout"

step "resetting hax_explorer and Redis db 14"
.venv/bin/python apps/web/e2e/prepare.py --target explorer

AUTH_ENV=(
  AUTH_SECRET=explorer-auth-secret-not-for-real-use-pad
  INTERNAL_API_SECRET=explorer-internal-secret-not-for-real-use
  AUTH_COOKIE_NAME=authjs.session-token
)
# Runs a command with the root .env, then these overrides, and nothing from
# this shell but HOME and PATH: every variable that picks a database, Redis,
# storage, mail, a secret or a URL is set here, so .env contributes only the
# keys and the model settings. It execs, so called with `&` its pid is the
# server's own and the cleanup's kill reaches it.
with_stack_env() {
  exec .venv/bin/python -c '
import os, sys
from dotenv import dotenv_values
env = {k: v for k, v in dotenv_values(sys.argv[1]).items() if v is not None}
env.update(HOME=os.environ["HOME"], PATH=os.environ["PATH"])
cut = sys.argv.index("--")
env.update(a.split("=", 1) for a in sys.argv[2:cut])
os.execvpe(sys.argv[cut + 1], sys.argv[cut + 1:], env)
' "$root/.env" "${AUTH_ENV[@]}" \
    DATABASE_URL=postgresql://hax_app:hax_app@localhost:5432/hax_explorer \
    MIGRATIONS_DATABASE_URL=postgresql://hax:hax@localhost:5432/hax_explorer \
    REDIS_URL=redis://localhost:6379/14 \
    CORS_ALLOW_ORIGINS=http://localhost:$WEB APP_BASE_URL=http://localhost:$WEB \
    S3_ENDPOINT_URL=http://localhost:9000 S3_BUCKET=hax-explorer S3_REGION=us-east-1 \
    S3_ACCESS_KEY_ID=hax S3_SECRET_ACCESS_KEY=haxhaxhax \
    SMTP_HOST=localhost SMTP_PORT=1025 SMTP_FROM=explorer@example.com SMTP_USER= SMTP_PASSWORD= \
    EMAIL_RECIPIENT=explorer@example.com BOOTSTRAP_USER_EMAIL= \
    AUTH_REQUIRE_EMAIL_VERIFICATION=true DEMO_TURN_LIMIT=3 ANON_PER_IP_PER_DAY=50 \
    LOG_LEVEL=INFO -- "$@"
}

wait_for() { # url seconds
  local deadline=$(( $(date +%s) + $2 ))
  until curl -sf -o /dev/null "$1"; do
    (( $(date +%s) < deadline )) || { echo "explorer: $1 did not answer in $2s"; return 1; }
    sleep 2
  done
}

step "starting the API and the worker"
# Options before the app path, and --app instead of -A: `make dev-stop`
# matches "uvicorn apps.api.main:app" and "celery -A apps.worker.celery_app",
# and must not stop this stack.
with_stack_env .venv/bin/python -m uvicorn --port $API apps.api.main:app > "$run_dir/api.log" 2>&1 &
pids+=($!)
with_stack_env .venv/bin/celery --app apps.worker.celery_app worker -Q ingest,celery \
  --pool=solo --loglevel=info --hostname "explorer@%h" > "$run_dir/worker.log" 2>&1 &
pids+=($!)
wait_for "http://localhost:$API/api/health" 60

step "building the web"
WEB_ENV=(HOME="$HOME" PATH="$PATH" "${AUTH_ENV[@]}"
  NEXT_PUBLIC_API_URL=http://localhost:$API API_INTERNAL_URL=http://localhost:$API
  AUTH_URL=http://localhost:$WEB AUTH_TRUST_HOST=true
  AUTH_GOOGLE_ID=explorer-unused AUTH_GOOGLE_SECRET=explorer-unused)
(cd apps/web && env -i "${WEB_ENV[@]}" npm run build > "$run_dir/web-build.log" 2>&1)
(cd apps/web && exec env -i "${WEB_ENV[@]}" node_modules/.bin/next start -p $WEB > "$run_dir/web.log" 2>&1) &
pids+=($!)
wait_for "http://localhost:$WEB/" 60

step "exploring as $persona"
mcp="$run_dir/mcp.json"
jq -n --arg out "$run_dir" --arg origins "http://localhost:$WEB;http://localhost:$API;http://localhost:$MAILPIT_UI" '{mcpServers: {playwright: {
  command: "npx",
  args: ["-y", "@playwright/mcp@0.0.83", "--isolated", "--headless",
         "--allowed-origins", $origins, "--blocked-origins", "https://hax-ai.chat",
         "--output-dir", $out]}}}' > "$mcp"

prompt="You are the product explorer for hax, a chat product that answers questions from a person's own documents. You play the persona below, using the product in a real browser, and you record what confused you. You never read or change code: you know only what the screen shows.

The run:
- The site: http://localhost:$WEB. The only other page you may open is the email inbox at http://localhost:$MAILPIT_UI, where every email the site sends arrives, whatever the address.
- Signing up: use the fresh address explorer+$run_id@example.com and a password of your choosing; the verification email lands in that inbox. If signing up stops you for good, note it as a finding and log in instead as explorer@example.com with the password explorer-password-123.
- The file to upload: $dir/fixture.txt
- The notes file: $notes. Write it as you go; it is your memory between steps. Start it with a line naming the persona and the date $today.
- Screenshots: save each with a short numbered name (01-front-page.png, ...); they land in local/explorer/$run_id/. Name that path in the notes.
- Bounds: at most $turns messages sent to hax's chat. Stop early after three failed actions in a row (a click that did nothing, a page that did not load) and say so.
- End the notes with the persona's two sections, then a footer line: turns used: <n>; stopped on: <bound | completion | failures>.

$(cat "$personas_dir/persona-$persona.md")"

agent_started=$(date +%s)
set +e
(cd "$dir" && env -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL -u VOYAGE_API_KEY HAX_EXPLORER_RUN=1 \
  perl -e 'alarm shift; exec @ARGV' "$WALL_SECONDS" \
  claude -p "$prompt" --model "$model" --max-turns 800 --max-budget-usd "$budget" \
    --permission-mode dontAsk --tools "Read,Write,Edit" \
    --allowedTools "Write(./**)" "Edit(./**)" "mcp__playwright" \
    --disallowedTools "Read(**/.env*)" \
    --mcp-config "$mcp" --strict-mcp-config \
    --output-format json --no-session-persistence > "$run_dir/result.json" 2> "$run_dir/agent.err")
agent_exit=$?
set -e
minutes=$(( ($(date +%s) - agent_started + 59) / 60 ))

# The agent cannot see its own cost; the footer is the runner's.
footer=$(jq -r --arg m "$model" --arg min "$minutes" '"runner: model \($m); \($min) min; \(.num_turns) agent turns; $\(.total_cost_usd * 100 | round / 100); \(.usage.input_tokens + .usage.cache_read_input_tokens + .usage.cache_creation_input_tokens) input / \(.usage.output_tokens) output tokens; ended \(.subtype)\(if .is_error then " with an error: " + (.result | tostring | .[0:200]) else "" end)"' "$run_dir/result.json" 2>/dev/null) \
  || footer="runner: model $model; $minutes min; agent exit $agent_exit with no result (killed at the ${WALL_SECONDS}s bound, or failed: see local/explorer/$run_id/agent.err); cost unknown"
[[ -f "$notes" ]] || printf '# Explorer: %s, %s\n\nThe agent wrote no notes.\n' "$persona" "$today" > "$notes"
printf '\n%s\n' "$footer" >> "$notes"
echo "explorer: $footer"

if grep -q "^## Findings" "$notes"; then
  write_status done
else
  write_status failed "no Findings section in the notes ($footer)"
fi
echo "explorer $run_id: finished $(date)"
