---
name: feature-chain
description: Launch and shepherd the feature lane's build of one approved brief through the committed feature-chain workflow (build, gate, review, fix, evidence, ship, gate block); the controller's recipe, not the main lane's plan execution
---

# Feature chain

The chain is `.claude/workflows/feature-chain.js`: a deterministic sequence of agents that builds one approved brief in its own worktree and ends with a pull request and a gate block. The controller launches it, records its state in the ledger, and delivers the gate block. Nothing in the chain waits for a human; a decision it cannot make stops it with `blocked`.

## Preconditions

- The brief is `approved` in `local/features.json` and its `briefSha256` matches `shasum -a 256 local/briefs/<id>/brief.md` (a brief edited after approval is re-approved first).
- One chain builds one slice (skill `feature-brief`, section Slices): `id` is the slice's (`<id>-<n>`, or `<id>` for a one-slice feature) and `brief` is that slice's brief. Slice n+1 launches from main only after slice n has merged.
- Postgres and Redis are up (`make infra-up`); the main checkout has `.venv`, `apps/web/node_modules` and `.env`.
- At most two chains in flight to start (three once two pilots have been measured); two chains that touch the same files are run one after the other.

## Launch

1. `scripts/feature-worktree.sh <id>` → prints the worktree path (`.claude/worktrees/<id>`, branch `feat/<id>` from `origin/main`, with `.venv`, `.env` and `local/` symlinked in and `node_modules` cloned).
2. Ledger: `state: building`, `worktree`, `branch`.
3. Run the workflow with the token ceiling as the turn's directive (the brief's "Size and cost" names it; `+1500k` is the default):
   `Workflow({ name: "feature-chain", args: { id, brief: "<absolute path>/local/briefs/<id>/brief.md", worktree: "<absolute path>", repoRoot: "<absolute path>", branch: "feat/<id>", date: "<YYYY-MM-DD>", briefSha256: "<sha>", ship: true, plan: "max-5x" } })`
   `ship: false` runs everything but the commit, push and PR (the smoke tests use it).
4. While it runs, the main lane continues. The workflow returns `{ shipped, pr, stoppedAt, blockedOn, phases }`.

## After

- `stoppedAt` null and `shipped` true → ledger `state: pr`, `pr` URL; read `local/briefs/<id>/gate.md`, append **New to you** (against `local/FRONTLOADED.local.md`) and **Cost** (`.venv/bin/python scripts/chain_cost.py <runId>` gives tokens per phase from the agents' own transcripts; wall time from the run's completion notices, summed across a resume), record cost in the ledger, complete its **Your review** after looking at the screens yourself, and deliver it by loading skill `gate-block`, never from memory: the chat hand-off leads with Your review, then the evidence, reviews, test names and flags. The maintainer says merge or what to change.
- `stoppedAt` set → ledger `state: blocked` with `blockedOn`; put the decision in front of the maintainer (now, or in the digest). After the decision, relaunch with `resumeFromRunId`, the same args, and the decision as `rulings` (`[{ stage?, match, keywords?, ruling, note }]`). `stage` is the stage that stopped, `"Build"` or `"Fix"` (the default), and only that stage's prompt carries the ruling. At Build, `ruling` settles the decision the implementer named, and the resume reruns Build and everything after it, which was not cached anyway. At Fix, `ruling` is `"fix"` or `"defer"`, and `match` is a phrase of the finding's title, or every `keywords` entry is in it (case, `_` and `-` ignored). A resume replays only the unchanged prefix of agent calls: Fix rulings (without `keywords`) are pasted into the gate-fix prompt, so a run whose gate went red reruns that fix and every review whenever the Fix rulings change (about 1.6M for server-turn). A decision that changes the brief's design (a service, a schema, the UX) still goes through the brief, never a ruling. Before a resume, a stop on findings that restate an existing ruling in new words is answered with `keywords` on that ruling, never new rulings, and it is the controller's to make, not the maintainer's. Never amend the brief to carry a decision: every prompt carries the brief's hash, so a changed brief reruns the whole chain (about 1.3M tokens for pilot-76). Only a decision that changes the design itself goes back through the brief, a re-approval and a fresh run.
- Merged → ledger `state: merged`; `scripts/feature-worktree.sh --remove <id>`.

## Cost bounds

The chain has no loops: at most two build agents, three gates, six reviewers, twelve verifiers (the most severe findings; the rest are listed unverified), one fixer, one evidence agent, one shipper and one gate-block writer. A `+Nk` token directive in the launching message adds a hard ceiling on top and turns on per-phase token accounting in `chain.json`; without one, the run's total comes from its completion notice. Most of a run's cost is the review and the gate suites, so a one-line change costs nearly as much as a small feature.

## Smoke test (any change to the workflow)

Two runs with `ship: false` against throwaway briefs under `local/briefs/smoke*/`: a one-line change that must reach the gate block with every Conformance line `as specified` and `UNSHIPPED: Ship skipped`; a brief whose Interface leaves one point open, which must stop at `Build` with `blockedOn` naming it; then that run resumed with a `stage: "Build"` ruling settling the point, which must get past `Build`. Remove the worktrees afterwards (`scripts/feature-worktree.sh --remove <id>`).
