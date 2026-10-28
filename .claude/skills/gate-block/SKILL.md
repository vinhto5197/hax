---
name: gate-block
description: The hand-off format for a finished change, what the maintainer reads instead of the diff; the feature gate block (filled by the feature chain) and the main-lane gate block (one per slice), plus the public PR body
---

# Gate block

The maintainer reviews a finished change from one block, not from the diff. The block is complete before it is sent: evidence, reviews, test names, flags, what is new to them, and cost. A chain writes the feature block; the controller writes the main-lane block and, for both, adds "New to you" and cost.

## Opening, always

The problem in plain words, as a user or developer meets it, with jargon defined; then how the change fixes it. Only then the sections below. A reader who has forgotten the item must be able to review from the block alone.

## Ship, show or ask

Every PR and every bite is classed, and the class decides who merges:
- **Ship** — tests, docs, comments, copy, dev tooling, small logic with a unit test and no user-visible change: the controller merges after its own review, and the digest lists it as merged.
- **Show** — user-visible behaviour, touching no schema, auth, infra or deploy path: it carries a journey for everything a browser can observe (a unit test only for what a test alone can stage); the controller checks the branch out, looks at desktop and phone width, and merges without waiting for the maintainer, like Ship. The maintainer gets a **short brief**, not the full block: what changed for users in a line or two, and anything worth knowing (a screenshot path, a call the controller made). No review section: nothing waits on them.
- **Ask** — schema, auth, isolation, infra, deploy, data deletion, anything irreversible, any design decision: nothing merges until the maintainer has read it; the full block (problem, fix, tests, flags, the hunks to read) and its review section; the main lane's bite review.
A merge to main deploys, so Ship still means CI green and the post-deploy health check watched.

Where a change lands depends on who wrote it, not on its class. Work done with the maintainer in the main lane goes straight to `main` on their word ("commit", "push"), whatever its class, once the same checks CI runs have passed locally: the maintainer's word is the permission, and CI still gates the deploy, so a red push never reaches production (it only holds main red until fixed). A pull request is for authors who may not push to `main`: the unattended routines and the feature chain's agents.

## Your review, on every Ask

Every hand-off that waits for the maintainer (an Ask PR or bite, a feature PR, anything asking for their word) ends with **Your review**: what only a human can judge here, as a short checklist the maintainer can finish in minutes. What the machines already proved (CI, the gates, the reviews, the controller's own look at the screens) is stated in one line so the maintainer does not redo it. Then, numbered:
1. What to look at (a screenshot, a screen to try, a copy line), with the path or the steps.
2. **Decisions for you**: only what is genuinely the maintainer's (product behaviour users will notice, scope, a risk to accept, a cost), each one sentence with a recommendation; "None" when none, which should be common.
3. **Adds to the stack**: every new service or container (production, CI or the test stack), dependency (package, image, external API), table or column, environment variable, and production code that exists only for tests, one line each with why; "None" when none. Never folded into the calls, and a change that adds one is never Ship or Show.
4. **Calls I made**: technical choices the controller or a chain made, one line each, for information only; nothing waits on them, and the maintainer may overrule any. Never dressed up as a decision.
5. Code worth raising, only when there is some: `file:line` and why a human should read it (a security boundary, a choice the maintainer might make differently, a surprising pattern); otherwise "no code to read".
6. The word that ends the review ("merge", "commit", "approved").
Ship and Show need none: the controller merges them and the digest lists them.
Enforced, not remembered: a Stop hook (`.claude/hooks/review_gate.sh`) refuses to end a turn whose final message asks for a review word without this section; the message is already on screen by then, so the answer to it is the missing section alone, never a repeat.

## Provenance, per bite

One line each: who wrote it (the controller, an implementer agent, a chain stage), who reviewed it (fresh-eyes, adversarial lenses, the final reviewer), which tests cover it and who wrote those, and whether the mutation check ran. A "no" is stated, never omitted: the maintainer decides what to read from this line.

## The feature gate block

Filled by the feature chain from `feature.md` in this directory into `local/briefs/<id>/gate.md`; the controller appends **New to you** (concepts absent from `local/FRONTLOADED.local.md`) and **Cost** (from the chain's `chain.json`), delivers it in chat, and records cost in `local/features.json`.

Rules:
- A `DEVIATION` line in Conformance must point at a stop-and-report the maintainer answered; one that does not is a chain bug and is reported as such, not as a deviation.
- The PR body is `pr-body.md`, the public part only: never review findings, cost or "new to you" (the repository is public).
- Test names, never bodies; flag any test that pins a behaviour the controller is unsure is intended.

## The main-lane gate block

One block per slice, never a message per task. In order:
1. Status table: each task, done or not, its test command and result.
2. What shipped, one paragraph.
3. Deep-read list, in caller → leaves order: `file:line`, what to look at, the paired test named first. Deep read = a schema or boundary, a policy decision, a mechanism others depend on, new test infrastructure, anything the controller chose that the maintainer might choose differently.
4. Glance list: the glance-only files, and the glance line ranges inside the deep-read files, so the reader knows which lines to skip. Glance = mechanics, generated types, migrations matching the model, docstring hunks, boilerplate.
5. Open decisions, each with options and a recommendation.
6. Test names, grouped by file, flagged where unsure.
7. New to you.
8. Cost: tokens by phase and wall time; the session's own share is an estimate and says so.
9. The commit message the controller would use. The controller commits only on the maintainer's word.

## Walks

When the maintainer asks to walk the code rather than read the block: caller first, leaves as black boxes named by intent, and the real runtime flow (what runs before this unit, what follows each outcome). A new-task walk opens with the purpose in plain words, each file's purpose, a vocabulary list with every abbreviation expanded, and the data flow as a concrete scenario; compressed arrow chains only after the story has defined every node.
