---
name: morning-digest
description: The one message that opens a day: nightly PRs reviewed, feature-lane state, briefs waiting, explorer findings, spillover decisions, yesterday's cost; refill or pause the nightly routine; the Friday retro
---

# Morning digest

**Trigger:** the first message after the harness notes a date change. The maintainer reuses long sessions and works past midnight, so the trigger is news, not the clock. If the night's run has not happened yet, set `"pending": true` in `local/routine-marker.json` and check again on later messages.

## Sources

- The nightly routine: `RemoteTrigger list_runs` for the routine id in the marker; `get_run_log` for each run newer than `last_reported_run`; `gh pr list --search "head:routine/"`, `gh pr checks`, `gh pr diff`.
- The feature lane: `local/features.json` (every entry not `merged`) and each feature's `local/briefs/<id>/chain.json`.
- Briefs waiting: ledger entries with `state: brief`.
- Explorer findings: `local/explorer/*.md` newer than the last digest.
- Spillover: decisions the previous day ended on, from the session and the ledger's `blocked` entries.
- Cost: yesterday's `chain.json` files (exact) and the session meter (an estimate, labelled).

## Order

1. **Nightly PRs**, one block per PR: the problem in plain words, how the change fixes it, test names, flags, CI state, the verdict from reading the diff and its class — Ship (merged by the controller before the digest), Show (merged, with the hunks to read) or Ask (held) — per the gate-block skill; the run's session link. UI items get a look in the browser on the local stack.
2. **Features**, one line each: `<id> — <state>`; a `blocked` one names the decision it needs; a `pr` one links the PR and says the gate block is ready.
3. **Briefs waiting** for approval, with artifact URLs and open-decision counts.
4. **Explorer findings** worth promoting (each: what, evidence path, proposed lane) and the count dropped.
5. **Spillover decisions**, each with options and a recommendation.
6. **Yesterday's cost** by lane, tokens and window share; the main lane marked estimate.
7. **New to you.**

Then the main item.

## After the maintainer's merges

Cross off merged items in `local/DEV_BACKLOG.local.md` (PR number beside each), note why for closed ones, update the marker's `last_reported_run`. Refill the routine's queue from the backlog's `[R]` items with full context per item (the template is `docs/routines/nightly-prompt.md`; at most ten items; the routine opens no new PR while ten are open), pulling any item a feature in flight would collide with; then clear the routine's connectors, which the service re-attaches by default. If every `[R]` item has a PR in some state, pause the routine (`enabled: false`) and re-enable it at the next refill.

## Friday

The digest gains a retro, at most fifteen lines: the week's recurring mistakes and the structure that absorbs each (a lint rule, a CI check, a test, a skill edit; a memory note only when nothing structural fits); cost by lane for the week against the previous one; changes to the brief template or the chain the week's gate blocks argue for.
