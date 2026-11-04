---
name: gate-block
description: The hand-off format for a finished change, what the maintainer reads instead of the diff; the feature gate block (filled by the feature chain) and the main-lane gate block (one per bite, bites built and reviewed in sequence), plus the public PR body
---

# Gate block

The maintainer reviews a finished change from one block, not from the diff. The block is complete before it is sent: evidence, reviews, test names, flags and cost. A chain writes the feature block; the controller writes the main-lane block and, for both, adds cost. New concepts are front-loaded in the brief ("New to you", skill feature-brief), before the build, never at the hand-off.

## Opening, always

The problem in plain words, as a user or developer meets it, with jargon defined; then how the change fixes it. Only then the sections below. A reader who has forgotten the item must be able to review from the block alone.

## Ship, show or ask

Every PR and every bite is classed, and the class decides who merges:
- **Ship** — tests, docs, comments, copy, dev tooling, small logic with a unit test and no user-visible change: the controller merges after its own review, and the digest lists it as merged.
- **Show** — user-visible behaviour, touching no schema, auth, infra or deploy path: it carries a journey for everything a browser can observe (a unit test only for what a test alone can stage); the controller checks the branch out, looks at desktop and phone width, and merges without waiting for the maintainer, like Ship. The maintainer gets a **short brief**, not the full block: what changed for users in a line or two, and anything worth knowing (a screenshot path, a call the controller made). No review section: nothing waits on them.
- **Ask** — schema, auth, isolation, infra, deploy, data deletion, anything irreversible, any design decision: nothing merges until the maintainer has read it; the full block (problem, fix, tests, flags, the hunks to read) and its review section; the main lane's bite review.
A merge to main deploys, so Ship still means CI green and the post-deploy health check watched.

Where a change lands depends on who wrote it, not on its class. Work done with the maintainer in the main lane goes straight to `main` on their word ("commit", "push"), whatever its class, with no local CI run beyond the pre-commit hooks: the maintainer's word is the permission, and GitHub's CI gates the deploy, so a red push never reaches production (it only holds main red until fixed). The controller watches the push's run and, when it is green, the post-deploy health check, in the background, and reports both; a red run's fix is a bite of its own, ahead of any shelved bite or new item. GitHub's failure email covers only a run that ends after the session does, so a session's first push checks main's last run first (`gh run list --branch main -L1`). The full `make ci` is only for the digest's one-push merge (skill `morning-digest`): CI ran each PR alone, never the combination. A pull request is for authors who may not push to `main`: the unattended routines and the feature chain's agents.

## Your review, on every Ask

Every hand-off that waits for the maintainer (an Ask PR or bite, a feature PR, anything asking for their word) ends with **Your review**: what only a human can judge here, as a short checklist the maintainer can finish in minutes. What the machines already proved (for a main-lane bite: its tests and the pre-commit hooks, since CI is reported after the push; otherwise CI, the gates, the reviews, the controller's own look at the screens) is stated in one line so the maintainer does not redo it. Then, numbered:
1. What to look at (a screenshot, a screen to try, a copy line), with the path or the steps.
2. **Decisions for you**: only what is genuinely the maintainer's (product behaviour users will notice, scope, a risk to accept, a cost), each one sentence with a recommendation; "None" when none, which should be common.
3. **Adds to the stack**: every new service or container (production, CI or the test stack), dependency (package, image, external API), table or column, environment variable, and production code that exists only for tests, one line each with why; "None" when none. Never folded into the calls, and a change that adds one is never Ship or Show.
4. **Calls I made**: technical choices the controller or a chain made, one line each, for information only; nothing waits on them, and the maintainer may overrule any. Never dressed up as a decision.
5. Code worth raising, only when there is some: `file:line` and why a human should read it (a security boundary, a choice the maintainer might make differently, a surprising pattern); otherwise "no code to read".
6. The word that ends the review ("merge", "commit", "approved").
Ship and Show need none: the controller merges them and the digest lists them.
Enforced, not remembered: a Stop hook (`.claude/hooks/review_gate.sh`) refuses to end a turn whose final message is a hand-off (it names a PR or a brief card's link, or carries a gate block as a heading) and asks for a review word without this section; a plain ask (a status answer, "say commit" for a small edit) needs none; the message is already on screen by then, so the answer to it is the missing section alone, never a repeat.

## Provenance, per bite

One line each: for a main-lane bite, its review tier (skill `blind-tests`, Review tiers) and, for a tier-1 change that skipped the adversarial review, the reason; who wrote it (the controller, an implementer agent, a chain stage), who reviewed it (fresh-eyes, adversarial lenses, the final reviewer), which tests cover it and who wrote those, and whether the mutation check ran. A "no" is stated, never omitted: the maintainer decides what to read from this line.

## The feature gate block

Filled by the feature chain from `feature.md` in this directory into `local/briefs/<id>/gate.md`; the controller appends **Cost** (from the chain's `chain.json`), delivers it in chat, and records cost in `local/features.json`.

Rules:
- A `DEVIATION` line in Conformance must point at a stop-and-report the maintainer answered; one that does not is a chain bug and is reported as such, not as a deviation.
- The PR body is `pr-body.md`, the public part only: never review findings or cost (the repository is public).
- Test names, never bodies; flag any test that pins a behaviour the controller is unsure is intended.

## Bites (main lane)

A main-lane item is cut into bites when it is planned: a bite is one or more of the plan's tasks, small enough for the maintainer to read its gate block and diff in one sitting (10–15 minutes). Each bite is built, checked (its tests and the pre-commit hooks), reviewed and committed on the maintainer's word, one commit per bite, before the next bite starts. Bites are never combined into one review; when combining looks cheaper, say so and the maintainer decides.
- **Order by what the reviewer needs in the tree to check the bite, never by risk tier.** For a fix-up item, for example:
  - first what surfaces the problem: the tool and its config, reporting but not yet gated;
  - then the fixes, each with its visible effect: a count that drops, a test that turns green (a failing test ships in the same bite as its fix);
  - last the enforcement that requires the clean state: a CI step, a hook, a gate.
- **Each bite stands on its own:** it is built to pass CI with this bite committed and the later bites still shelved.
- **Only the current bite's files are in the tree;** the later bites wait under `local/shelf/<item>/`, and that folder is deleted when the item's last bite is committed, so a shelf never outlives its item.
- **Each bite carries its own review:** its tier, its fresh-eyes reviewer, blind tests where it changes behaviour, and its own gate block.
- **The adversarial review runs once per item, not per bite:** when any bite is tier 1, one run over the item's whole commit range is offered after its last tier-1 bite (cost preview, the maintainer's "go"); its findings become a fix bite.

## The main-lane gate block

One block per bite, never a message per task. In order:
1. Status table: each task, done or not, its test command and result.
2. What shipped, one paragraph.
3. Deep-read list, in caller → leaves order: `file:line`, what to look at, the paired test named first. Deep read = a schema or boundary, a policy decision, a mechanism others depend on, new test infrastructure, anything the controller chose that the maintainer might choose differently.
4. Glance list: the glance-only files, and the glance line ranges inside the deep-read files, so the reader knows which lines to skip. Glance = mechanics, generated types, migrations matching the model, docstring hunks, boilerplate.
5. Open decisions, each with options and a recommendation.
6. Test names, grouped by file, flagged where unsure.
7. Cost: tokens by phase and wall time; the session's own share is an estimate and says so.
8. The commit message the controller would use. The controller commits only on the maintainer's word.

## Walks

When the maintainer asks to walk the code rather than read the block: caller first, leaves as black boxes named by intent, and the real runtime flow (what runs before this unit, what follows each outcome). A new-task walk opens with the purpose in plain words, each file's purpose, a vocabulary list with every abbreviation expanded, and the data flow as a concrete scenario; compressed arrow chains only after the story has defined every node.
