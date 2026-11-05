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

1. **Nightly PRs**, by class (gate-block skill). The controller does only what needs the main session, then hands the merging to one background agent (the maintainer, 2026-11-04: nobody waits on it and the main lane goes on), and the maintainer hears only what needs them.
   **The main session first:** classify every open nightly (`routine/*`) and journeys-sweep (`journey/sweep-*`) PR (Sources gives the sweep's own checks); a PR whose browser look is due (each Show PR, a journeys sweep's screens) gets it now, on the local stack at desktop and phone width, since a look needs the stack's ports and the one shared browser (the stack from the PR's worktree, under the main checkout's environment, `main=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")`: `direnv exec "$main" .venv/bin/uvicorn apps.api.main:app --port 8000` and, in `apps/web`, `NEXT_PUBLIC_API_URL=http://localhost:8000 direnv exec "$main" npm run dev`, both in the background; plus `direnv exec "$main" make worker` when the look sends email or ingests a file); a PR that changed `constraints.txt` is merged by the main session itself (the `.venv` is shared with the main lane, and the agent must not reinstall it).
   **The background merge** (one agent, this recipe, the PR list with each PR's class and look result):
   - **One fresh-eyes reviewer over the night's PRs** (the maintainer, 2026-11-04) before any merge: a fresh agent reads every PR's diff caller-first (not the routine's own report) and returns real defects with file:line and a scenario; PRs touching input validation, error surfaces or anything near auth are named to it first. The routines have no reviewer of their own. Each finding is fixed in the merge worktree, as a commit on top of the merges (step 3), or the PR is held; never on the PR's own branch, whose push only starts a CI run that the combination's checks already cover. The PR still shows MERGED: its own head commit reaches main through the merge (step 5 checks).
   - **Merging is one push** (the maintainer, 2026-11-04, CI cost; each merge to main otherwise costs one full CI run and one deploy). Merged: Ship PRs, and Show PRs whose look passed. Held, unmerged: Ask PRs, a look that failed or has not happened, and a PR behind a conflict that keeping both sides verbatim does not resolve.
   0. Main's last CI run (`gh run list --branch main -L1`): red, the agent stops and reports; nothing merges (the fix is a main-lane bite).
   1. `scripts/feature-worktree.sh merge-<YYYY-MM-DD>` (from `origin/main`, `.venv`, `.env` and `local/` linked; never the main checkout, whose uncommitted edits or unpushed commits would ride along), then `git fetch origin` in it.
   2. `git merge --no-ff origin/<branch>` for each PR being merged (never squashed: GitHub marks a PR merged only when its own commits reach main).
   3. `(cd apps/web && npm ci)` when a merged PR changed `apps/web/package-lock.json` (the worktree's node_modules is a copy of the main checkout's); the review's fixes as commits on top; then `make ci` from the worktree's root (Docker running, `make infra-up` done): CI's checks on a combination CI has never run (each PR ran alone). Red: one fix and one rerun; red again, the PR it implicates is held (recreate the worktree from `origin/main`, merge the rest, reapply their fixes, `make ci` again); red with no PR to blame: stop and report.
   4. `git push origin HEAD:main`. Rejected because main moved: never force; `git fetch origin && git merge origin/main`, `make ci` again, push again; after a second rejection, report instead of retrying.
   5. Wait until each PR shows MERGED (`gh pr view <n> --json state`, retrying for up to a minute), then check their branches are gone (the repository deletes a merged PR's branch; `git push origin --delete <branch>` only for one left behind, never for a PR that is not MERGED) and, from the main checkout, `scripts/feature-worktree.sh --remove --force merge-<YYYY-MM-DD>`.
   6. Watch the push's CI run and the post-deploy health check (skill `gate-block`, Ship). Red: report it; its fix is a main-lane bite.
   **The agent's report** to the controller: the PRs merged, the fixes it made, `make ci`, main's CI and the deploy's health, each held PR with its reason. **To the maintainer**, only: each Ask PR's full block (problem, fix, test names, flags, the hunks to read) and its review section; each Show PR's short brief (what changed for users, anything worth knowing); each held conflict or failure; the merged count with CI and deploy in one line; the run's session link once. A PR held for a look or a fix goes into the next background merge, the same recipe.
2. **Features**, one line each: `<id> — <state>`; a `blocked` one names the decision it needs; a `pr` one links the PR and says the gate block is ready.
3. **Briefs waiting** for approval, with artifact URLs and open-decision counts.
4. **Explorer findings** worth promoting (each: what, evidence path, proposed lane) and the count dropped.
5. **Spillover decisions**, each with options and a recommendation.
6. **Yesterday's cost** by lane, tokens and window share; the main lane marked estimate.

Then the main item.

## After the maintainer's merges

Cross off merged items in `local/DEV_BACKLOG.local.md` (PR number beside each), note why for closed ones, update the marker's `last_reported_run`. Refill the routine's queue from the backlog's `[R]` items with full context per item; an item estimated over ~120 changed lines is split before it is queued. An item that touches what the model sees or does (`evals/README.md`, "When a change must run it") is never queued: the routine cannot run the eval, so it goes to the main lane. An item that guards against a failure nobody has seen ("this could happen") is queued only with evidence that it can: a reproduction, the source line that produces it, or an incident; without one it becomes `[H:verify]` and goes to the maintainer as a question, never to the routine (the queue text lives in `local/routine-queue.md` and fills the template `docs/routines/nightly-prompt.md`; at most ten items; the routine opens no new PR while ten are open), pulling any item a feature in flight would collide with; then clear the routine's connectors, which the service re-attaches by default. If every `[R]` item has a PR in some state, pause the routine (`enabled: false`) and re-enable it at the next refill.

## The week file

`local/retro/<ISO week>.md` is the retro's memory across sessions and compactions. One line per occurrence: `- YYYY-MM-DD [category] what happened`, with no proposed fix (a fix proposed per line is how the process grew a piece per mistake; 107, 2026-11-02), categories from: forgot, yes-man, wrong-design, overclaim, scope-creep, tool-quirk, routine-abandon, ci-red, flake, review-miss, process. The hook counts them on Friday; two or more in a category is recurring. Three sources write to it, so no single one has to be reliable:

1. **On the spot**, by the controller: a correction from the maintainer, a refused tool call, a mistake repeated, a process decision.
2. **Each digest**, from the hard sources: an abandoned routine item, a PR red after three attempts, a `fixme` journey, a reviewer's HOLD, an explorer run that stopped on a failure.
3. **Friday, from the transcripts**: `.venv/bin/python scripts/week_transcript.py` prints the week's typed messages from the maintainer and every refused or failed tool call from the never-compacted transcripts; a fresh agent (Sonnet) reads that output beside the week file and returns the occurrences the file is missing, which are appended before the tally is read.

## Friday

After the digest, the retro: read the hook's tally, run source 3, then write at most fifteen lines: the week's recurring mistakes and, for each, first what can be deleted or simplified, and only then the smallest change that absorbs it (a line in an existing skill, CLAUDE.md or memory index; a new script, hook or skill only when it retires one); the index sweep: a fresh agent compares every `MEMORY.md` line with its memory file and every drift is fixed, since only the index survives a compaction; cost by lane for the week against the previous one; changes to the brief template or the chain the week's gate blocks argue for.
