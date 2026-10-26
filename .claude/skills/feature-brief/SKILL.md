---
name: feature-brief
description: Write, review and publish a feature-lane brief; approval makes it the spec
---

# Feature brief

A brief is the complete design of one feature-lane item, written by the orchestrator without a live conversation and approved by the maintainer once. After approval the brief is the spec: the implementer builds exactly what it says, the blind test writer tests exactly its Interface, and any choice the brief does not settle stops the build instead of being guessed. Approval also pre-authorizes the feature chain's branch commits, push and pull request; the merge still waits for the maintainer's word.

## Where things live

- The brief: `local/briefs/<id>/brief.md`, from `template.md` in this directory; the chain writes its outputs beside it (`gate.md`, `chain.json`, `evidence/`).
- The ledger: `local/features.json`, `{"features": [...]}`, one entry per feature:
  `{id, title, state, brief, briefSha256, artifactUrl, worktree, branch, pr, cost: {brief, build, tests, reviews, fixes, total}, updated}`
  with `state` one of `candidate | brief | approved | building | reviewing | blocked | pr | merged`. The orchestrator is the only writer; a chain never edits it.
- The design reviewer's prompt: `design-reviewer.md` in this directory.

## Steps

1. **Read.** The backlog item, the code it touches, the tests that cover that code, the ADRs it brushes. Decide the lane: a brief is for a medium item with a design to settle; a small item goes to the nightly queue.
2. **Write** `local/briefs/<id>/brief.md` from the template. Every section present, in order, with the template's headings. Open decisions ideally empty: a decision the orchestrator can make with evidence is a call under Calls made, with the rejected alternative. The Interface section is frozen: it is what both the implementer and the test writer code against.
3. **Design review.** Dispatch a fresh general-purpose agent with `design-reviewer.md`. On `ready`, record the verdict under Calls made and keep any objections worth keeping as calls. On `revise`, change the brief, record what changed, and dispatch the reviewer once more; a second `revise` goes to the maintainer as an open decision, not a third round.
4. **Publish.** Publish `brief.md` as a private artifact titled `<id> brief` (Markdown is the intended format for a brief: this skill asks for it). Add or update the ledger entry: `state: brief`, `artifactUrl`, `briefSha256` from `shasum -a 256 local/briefs/<id>/brief.md`, `updated` now.
5. **Hand over.** Tell the maintainer the brief is waiting, with the artifact URL and the count of open decisions. The morning digest lists briefs waiting.
6. **Approval.** The maintainer comments on the artifact or replies in chat. A comment that asks for a change: revise the file, republish to the same URL, update `briefSha256`, answer the comment. "approved" (on the artifact or in chat): set `state: approved`; the chain may start (skill `feature-chain`). The hash in the ledger is the version that was approved; the chain refuses a brief whose hash has changed since.

## Rules

- No strategy, no product plans beyond the feature itself, in the brief: it will be summarized in a public PR body.
- A brief that needs the maintainer's attention mid-build has failed its job; when that happens, the stop-and-report goes into the ledger entry as `state: blocked` with the decision needed, and the brief is amended before the chain resumes.
- Credit lifted text at the bottom of the template, never in the brief.
