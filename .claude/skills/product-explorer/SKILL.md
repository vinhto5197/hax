---
name: product-explorer
description: The weekly unattended run that uses the product as a persona in a local browser and files what confused it as candidate backlog items with evidence; started by the due hook on Fridays, never edits code, never touches production
---

# Product explorer

The unattended lane's weekly look at the product from outside: an agent uses main's build the way one persona would and records what confused it. Its output is findings with evidence, never code. It is bounded, so its cost is known before it starts, and it runs only on a local stack of its own.

## How it runs

`scripts/explorer.sh` is the whole run. The due hook (`.claude/hooks/due.sh`) starts it in the background on the first prompt from Friday on, once per ISO week, so it explores while the morning's reviews happen; the hook prints `[due] EXPLORER LAUNCHED`, or `EXPLORER WAITING` with the reason when a run cannot start (Docker down, a port taken) and tries again on the next prompt.

- **The stack:** a worktree of `origin/main`; web :3002, API :8002, database `hax_explorer` and Redis db 14 (emptied each run by `apps/web/e2e/prepare.py --target explorer`), one worker for both queues, the dev S3 stand-in and dev Mailpit. The real model, because the scripted e2e model cannot produce a confusing answer. Nothing the dev stack (:3000/:8000) or the journeys (:3001/:8001) use is shared, and the runner stops only what it started.
- **The agent:** a headless `claude -p` in `dontAsk` mode: the browser (Playwright MCP, allowed origins :3002, :8002 and Mailpit's inbox :8025 only), and Write and Edit inside `local/explorer/` only. It signs up with a fresh address and verifies through the inbox, as a person would, with a seeded login as the fallback. It never sees the model keys.
- **The persona:** the `persona-*.md` files here, rotated by ISO week (`scripts/explorer.sh --persona` names this week's). A new persona is one new file. Each one says what to do in order and how to report.
- **Bounds:** 40 messages to hax's chat, $15 of agent spend on Sonnet (a two-message smoke run cost $0.33 in 45 agent turns), one hour of wall clock, and three failed actions in a row. Knobs for a run by hand are in the script's header.
- **Output:** `local/explorer/<date>-<persona>.md`, ending with `## Findings`, `## Did not get to`, the agent's footer, and the runner's footer with the model, minutes, agent turns, cost and tokens. Screenshots and the stack's logs are in `local/explorer/<date>-<persona>/`.

When the run ends, the hook prints `[due] EXPLORER DONE` (or `FAILED` with the reason and the logs) on every prompt until `.claude/hooks/due.sh mark explorer`.

## After the run

The digest triages the findings. Each becomes one of: a backlog item marked `[R]` when it is small and needs no decision; a candidate for the feature lane (a brief) when it needs a design; or dropped, with the reason kept in the notes file. A finding is never promoted without its screenshot. A `## Triage (<date>)` footer in the notes file records the outcome and the hit rate (promoted findings against the run's cost), which the Friday retro reads.

A failed run is a week-file line (`[routine-abandon]`) with its reason; rerun it by hand (`scripts/explorer.sh`) or let the week go.

<!-- bounded loop, notes-as-memory and abort-after-repeated-failure after Kun Chen's gnhf -->
