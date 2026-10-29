---
name: feature-brief
description: Write, review and publish a feature-lane brief; approval makes it the spec
---

# Feature brief

A brief is the complete design of one feature-lane item, written by the orchestrator without a live conversation and approved by the maintainer once. After approval the brief is the spec: the implementer builds exactly what it says, the blind test writer tests exactly its Interface, and any choice the brief does not settle stops the build instead of being guessed. Approval also pre-authorizes the feature chain's branch commits, push and pull request; the merge still waits for the maintainer's word.

## Where things live

- The brief: `local/briefs/<id>/brief.md`, from `template.md` in this directory, is the spec the agents build from. The card: `local/briefs/<id>/<id>.md` (the filename is the artifact's title), from `card.md` in this directory, is what the maintainer reads and approves: one screen, manager-level, no code; the chain writes its outputs beside it (`gate.md`, `chain.json`, `evidence/`).
- The ledger: `local/features.json`, `{"features": [...]}`, one entry per feature:
  `{id, title, state, brief, briefSha256, artifactUrl, worktree, branch, pr, cost: {brief, build, tests, reviews, fixes, total}, updated}`
  with `state` one of `candidate | brief | approved | building | reviewing | blocked | pr | merged`. The orchestrator is the only writer; a chain never edits it.
- The design reviewer's prompt: `design-reviewer.md` in this directory.
- A sliced feature: `local/briefs/<id>/brief.md` is the whole design, with its Slices section; each slice has its own brief `local/briefs/<id>-<n>/brief.md` (the template, scoped to that slice, its Interface frozen for that slice alone) and its own ledger entry `<id>-<n>` with `parent: <id>`. One card for the feature, listing the slices. A feature that fits one slice has only `<id>`, as before.

## Slices

Every pull request the lane opens is one the maintainer can review whole. The slice limit: about **300 changed lines the maintainer reads**, meaning production code, test infrastructure (fakes, fixtures, config), CI, infra and docs. Test files (read by name) and generated types are not counted. The plan decides the slicing before the card, never after the build:
- A feature estimated over the limit is cut into slices, each under it.
- Each slice merges and deploys on its own, leaving main releasable. A slice that only makes sense with the next one is not a slice.
- The order is the build order: slice n+1's chain starts from main after slice n has merged.
- Each slice carries its own journeys and tests, and its own share of the testing map, the ADR and the docs.
- Slice briefs are written with the feature brief and approved with its card. When a merged slice changes something a later slice's brief relies on, that brief is amended and its line on the card re-approved before its chain starts.

## Steps

1. **Read.** The backlog item, the code it touches, the tests that cover that code, the ADRs it brushes. Decide the lane: a brief is for a medium item with a design to settle; a small item goes to the nightly queue.
2. **Write** `local/briefs/<id>/brief.md` from the template. Size it first, line by line per file, and slice it when it is over the limit (section Slices above); then write each slice's brief. Every section present, in order, with the template's headings. Open decisions ideally empty: a decision the orchestrator can make with evidence is a call under Calls made, with the rejected alternative. The Interface section is frozen: it is what both the implementer and the test writer code against.
3. **Design review.** Dispatch a fresh general-purpose agent with `design-reviewer.md`. On `ready`, record the verdict under Calls made and keep any objections worth keeping as calls. On `revise`, check each objection against the code (an objection that does not hold is recorded as refuted, with the reason), change the brief for the ones that hold, record what changed, and dispatch a fresh reviewer on the new version. Repeat until a round returns `ready`: a round whose objections change nothing that gets built. A reviewer told to argue against a design always finds something, so the stop is "nothing that changes the build", not "nothing at all". Four rounds at most (about 85k tokens each); a fourth `revise` goes to the maintainer as an open decision.
4. **Publish.** Write the card `<id>.md` from the brief (it states only what the brief decides) and publish it as a private artifact titled `<id>` (Markdown is the intended format for a card: this skill asks for it). The brief itself is never handed to the maintainer to read. Add or update the ledger entry: `state: brief`, `artifactUrl`, `briefSha256` from `shasum -a 256 local/briefs/<id>/brief.md`, `updated` now.
5. **Hand over.** Tell the maintainer the brief is waiting, with the artifact URL and the count of open decisions. The morning digest lists briefs waiting.
6. **Approval.** The maintainer comments on the artifact or replies in chat. A comment that asks for a change: revise the brief and the card, republish the card to the same URL, update `briefSha256`, answer the comment. "approved" (on the artifact or in chat): set `state: approved`; the chain may start (skill `feature-chain`). Approving the card approves the brief behind it, and every slice brief; the hash in each ledger entry is the version that was approved; the chain refuses a brief whose hash has changed since.

## Rules

- Build for typical users first: accessibility (ARIA roles and states beyond what a journey selector needs, screen-reader checks, keyboard-only navigation, focus traps and focus return, contrast-only fixes) is never part of a brief, in either lane. An accessibility point raised while writing or reviewing a brief becomes a backlog item for the nightly queue, written at that moment, and the brief does not carry it. Accessible names that journeys select by stay, as test hooks; Escape closing a dialog stays, as mouse-and-keyboard behaviour.

- No strategy, no product plans beyond the feature itself, in the brief: it will be summarized in a public PR body.
- A brief that needs the maintainer's attention mid-build has failed its job; when that happens, the stop-and-report goes into the ledger entry as `state: blocked` with the decision needed, and the brief is amended before the chain resumes.
- Credit lifted text at the bottom of the template, never in the brief.
