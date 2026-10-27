# scripts/ — ad-hoc dev utilities

One-off, **read-mostly** tools for poking at a running local stack (DB, etc.)
while developing. Not part of the app; not imported by it. Each script loads
the root `.env` itself, so you can run it from anywhere with the venv's deps
available (`packages`/`apps.api` resolve via the editable install).

| Script | What it does | Example |
|---|---|---|
| `corpus.py` | List ingested documents, or dump one document's chunk content | `python scripts/corpus.py` / `python scripts/corpus.py glimmerwick.md` |
| `set_password.py` | **Writes to the DB**: set/replace a user's password (claim the bootstrap account; local admin escape hatch) | `python scripts/set_password.py you@example.com` |

Add new utilities here as needed. Keep them read-only unless clearly named
otherwise (a destructive script should make that obvious).

## Dev-process helpers

Not utilities for poking at the stack: scripts the Makefile and the feature
chain call.

| Script | What it does |
|---|---|
| `with-lock.sh` | Runs one command under a directory lock (`mkdir` is the atomic primitive); `make test` and `make e2e` always use it where `local/` exists, so runs that share `hax_test` or the e2e stack queue instead of colliding. Exit 75 on timeout. |
| `feature-worktree.sh` | One git worktree per feature-lane build under `.claude/worktrees/<id>` on `feat/<id>`, with `.venv`, `.env` and `local/` symlinked and `node_modules` cloned; `--remove <id>` tears it down. |
| `explorer.sh` | The weekly product explorer: a persona from `.claude/skills/product-explorer/` uses main's build on an isolated stack (web :3002, API :8002, `hax_explorer`, Redis db 14) with the real model and writes its notes to `local/explorer/`. The due hook starts it on Fridays; `--check` says whether a run can start now. Spends real model money (bounded). |
| `chain_cost.py` | Tokens per phase of one feature-chain run (`chain_cost.py <runId>`), from its agents' own transcripts; the gate block's Cost section comes from it. Read-only. |
| `state.sh` | The project's live state from its sources (main's head, open PRs, the feature ledger, the nightly queue, the marks, the week's retro tally, the explorer), then the ordered next list from the backlog's START HERE; `--next` prints the list only. The due hook attaches it to the day's first prompt. Read-only. |
| `week_transcript.py` | Prints one ISO week of this project's Claude Code transcripts reduced to the maintainer's typed messages and every refused or failed tool call; the Friday retro reads it, because transcripts are never compacted. Read-only. |
