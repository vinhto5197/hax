---
name: gate-block
description: The hand-off format for a finished change, what the maintainer reads instead of the diff; the feature gate block (filled by the feature chain) and the main-lane gate block (one per slice), plus the public PR body
---

# Gate block

The maintainer reviews a finished change from one block, not from the diff. The block is complete before it is sent: evidence, reviews, test names, flags, what is new to them, and cost. A chain writes the feature block; the controller writes the main-lane block and, for both, adds "New to you" and cost.

## Opening, always

The problem in plain words, as a user or developer meets it, with jargon defined; then how the change fixes it. Only then the sections below. A reader who has forgotten the item must be able to review from the block alone.

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
