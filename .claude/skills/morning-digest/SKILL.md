---
name: morning-digest
description: The one message that opens a day: nightly PRs reviewed, feature-lane state, briefs waiting, explorer findings, spillover decisions, yesterday's cost; refill or pause the nightly routine; the Friday retro
---

# Morning digest

**Trigger:** the `due` hook (`.claude/hooks/due.sh`, on every prompt) prints `[due] DIGEST DUE` while the marker's `last_digest_date` is not today, and `[due] RETRO DUE` from Friday until the week's retro is marked. A `[due]` line is answered before anything else in the message. "BAU" from the maintainer means: do what the hook lists. Finish each with `.claude/hooks/due.sh mark digest` or `mark retro`; until then the reminder repeats on every message, which is the intended failure mode. If the night's run has not happened yet, set `"pending": true` in `local/routine-marker.json` and check again on later messages.

## Sources

- The nightly routine: `RemoteTrigger list_runs` for the routine id in the marker; `get_run_log` for each run newer than `last_reported_run`; `gh pr list --search "head:routine/"`, `gh pr checks`, `gh pr diff`. The weekly journeys sweep (`journeys_routine_id` in the marker; cron Friday 06:00 UTC; template `docs/routines/journeys-prompt.md`, no queue) the same way: runs newer than `journeys_last_reported_run`, its one PR under `head:journey/sweep-`. Before merging, green or red: check the branch out, run its new or changed specs locally (`make e2e ARGS="<spec files>"`; it waits for the gate lock), and look at the screens they touch with the Playwright MCP at desktop and phone width. Green, passing locally and looking right → Ship; a `fixme` names a product bug → a backlog item and a week-file line; "Gaps left" → backlog items (`J*`/`J†` gaps join the fixtures brief). A sweep with no gaps is a one-line cursor PR: Ship.
- The feature lane: `local/features.json` (every entry not `merged`) and each feature's `local/briefs/<id>/chain.json`.
- Briefs waiting: ledger entries with `state: brief`.
- Explorer findings: `local/explorer/*.md` newer than the last digest. The weekly run is started by the due hook from Friday's first prompt and reported by it (`[due] EXPLORER DONE` or `FAILED`) until `.claude/hooks/due.sh mark explorer`; triage it per skill `product-explorer`, in that day's digest or the next.
- Spillover: decisions the previous day ended on, from the session and the ledger's `blocked` entries.
- Cost: yesterday's `chain.json` files (exact) and the session meter (an estimate, labelled).

## Order

1. **Nightly PRs**, by class (gate-block skill), never collapsed into one table: **Ship** — one line each, merged by the controller before the digest; **Show** — merged by the controller after its look in the browser on the local stack, then a short brief each: what changed for users in a line or two, and anything worth knowing; **Ask** — held, the full block each (problem, fix, test names, flags, the hunks to read) and its review section. A PR waiting on a fix the controller can make is fixed first, not handed over. The run's session link once.
2. **Features**, one line each: `<id> — <state>`; a `blocked` one names the decision it needs; a `pr` one links the PR and says the gate block is ready.
3. **Briefs waiting** for approval, with artifact URLs and open-decision counts.
4. **Explorer findings** worth promoting (each: what, evidence path, proposed lane) and the count dropped.
5. **Spillover decisions**, each with options and a recommendation.
6. **Yesterday's cost** by lane, tokens and window share; the main lane marked estimate.
7. **New to you.**

Then the main item.

## After the maintainer's merges

Cross off merged items in `local/DEV_BACKLOG.local.md` (PR number beside each), note why for closed ones, update the marker's `last_reported_run`. Refill the routine's queue from the backlog's `[R]` items with full context per item (the queue text lives in `local/routine-queue.md` and fills the template `docs/routines/nightly-prompt.md`; at most ten items; the routine opens no new PR while ten are open), pulling any item a feature in flight would collide with; then clear the routine's connectors, which the service re-attaches by default. If every `[R]` item has a PR in some state, pause the routine (`enabled: false`) and re-enable it at the next refill.

## The week file

`local/retro/<ISO week>.md` is the retro's memory across sessions and compactions. One line per occurrence: `- YYYY-MM-DD [category] what happened → the structure that would absorb it`, categories from: forgot, yes-man, wrong-design, overclaim, scope-creep, tool-quirk, routine-abandon, ci-red, flake, review-miss, process. The hook counts them on Friday; two or more in a category is recurring. Three sources write to it, so no single one has to be reliable:

1. **On the spot**, by the controller: a correction from the maintainer, a refused tool call, a mistake repeated, a process decision.
2. **Each digest**, from the hard sources: an abandoned routine item, a PR red after three attempts, a `fixme` journey, a reviewer's HOLD, an explorer run that stopped on a failure.
3. **Friday, from the transcripts**: `.venv/bin/python scripts/week_transcript.py` prints the week's typed messages from the maintainer and every refused or failed tool call from the never-compacted transcripts; a fresh agent (Sonnet) reads that output beside the week file and returns the occurrences the file is missing, which are appended before the tally is read.

## Friday

After the digest, the retro: read the hook's tally, run source 3, then write at most fifteen lines: the week's recurring mistakes and the structure that absorbs each (a lint rule, a CI check, a test, a skill edit; a memory note only when nothing structural fits); cost by lane for the week against the previous one; changes to the brief template or the chain the week's gate blocks argue for.
