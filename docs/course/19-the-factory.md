# 19. The factory

Threads: C (building with Claude Code)

## The idea

Late in v0 the work stopped being one person and one AI session at a desk. It became three production lines, each with its own rules about who may decide, who may commit and who must look before anything ships. The lines are called **lanes** in [`CLAUDE.md`](../../CLAUDE.md), "Working lanes":

- **Main:** the maintainer and the controller (the main Claude session) work one item at a time, cut into small pieces.
- **Feature:** a written design is approved once, then a fixed sequence of agents builds it in its own copy of the repo and opens a pull request (a proposed change on GitHub that waits to be merged).
- **Unattended:** scheduled runs with no person present: a nightly routine, a weekly journeys sweep and a weekly product explorer. They make no decisions, and CI (continuous integration: the checks GitHub runs on every push) is their gate.

Like a factory line: no station can be skipped, and a person signs off only where judgment is needed.

## How hax does it

**The feature lane.** It starts with a **brief**, written from [`.claude/skills/feature-brief/`](../../.claude/skills/feature-brief/SKILL.md). The brief is the full spec, and its Interface section is frozen: the implementer and the blind test writer (chapter 16) both code against it. A fresh design-reviewer agent argues against the brief until a round "returns `ready`", four rounds at most. The maintainer then approves a one-screen **card**, not the brief itself (`7d91d25`). Approval pre-authorizes the branch's commits, push and pull request, but the merge still waits for the maintainer. Each pull request is capped at about 300 lines a person must read; bigger features are cut into slices.

The build is [`.claude/workflows/feature-chain.js`](../../.claude/workflows/feature-chain.js), committed in `8bff87d` on 2026-10-26. Its header lists the order: check the brief's hash (a short fingerprint computed from its text, which any edit changes) against the approved one → implementer and blind test writer in parallel → gate (lint, which flags style slips and likely mistakes; type checks; unit tests; journeys) → review (a fresh-eyes reviewer plus five adversarial lenses) → fix → re-review of the fix → gate again → evidence (journeys and screenshots at desktop and phone width) → ship (commit, push, PR) → gate block. "Deterministic order, so no agent can skip a review or ship over a red gate." The recipe for launching and steering it is [`.claude/skills/feature-chain/SKILL.md`](../../.claude/skills/feature-chain/SKILL.md).

**The hand-off.** Every finished change ends in a **gate block** ([`.claude/skills/gate-block/SKILL.md`](../../.claude/skills/gate-block/SKILL.md)): what the maintainer reads instead of the diff. It opens with the problem in plain words, then evidence, reviews, test names and cost. Each change is classed:

- **Ship** (tests, docs, tooling, small logic with a unit test): the controller merges.
- **Show** (user-visible behavior, no schema, auth or infra): the controller looks at the screens and merges; the maintainer gets a short note.
- **Ask** (schema, auth, isolation, infra, deploy, data deletion, anything irreversible, any design decision): nothing merges until the maintainer has read it, and the block ends with a **Your review** checklist of what only a human can judge.

In the main lane an item is cut into **bites**, each small enough to review in 10 to 15 minutes, each reviewed and committed in order. Bites may be built in parallel in worktrees (extra checkouts of the repo), but their gates "come out one at a time" (`ec0b073`).

**The unattended lane.** [`docs/routines/`](../../docs/routines/README.md) holds prompt templates for cloud routines. The nightly one ([`nightly-prompt.md`](../../docs/routines/nightly-prompt.md)) turns each queued item into one branch and one pull request. Its hard rules forbid touching migrations, auth, infra, CI or dependencies, and it abandons any diff over about 150 lines. The weekly journeys sweep writes Playwright journeys for user-visible changes that reached `main` without one. The **product explorer** ([`.claude/skills/product-explorer/SKILL.md`](../../.claude/skills/product-explorer/SKILL.md)) has an agent use the product as a persona in a local browser and file what confused it, with screenshots. It never edits code. The **morning digest** skill reviews the night's pull requests with a fresh-eyes reviewer before merging them.

## What was decided, and why

**One unattended lane, not two.** The first routine design (`60137a9`, 2026-10-21) had a second, private lane that committed locally. Half an hour later `ba8fd97` dropped it: "every branch of a public repo is public", and the tool that pulls a cloud session down moves its conversation, not its unpushed commits. So security-sensitive items, and anything touching auth, migrations, deploy or CI, are fixed by hand in the main lane. The queued items are never committed either, because "an item can describe a weakness before it is fixed".

**Approval of a card, not a diff.** The maintainer's judgment is spent on the design and on the gate block ("from one block, not from the diff"); everything between runs without a person. The cost: a long brief up front, and a build that stops rather than guesses when the brief leaves a choice open.

**Rejected:** agents choosing their own order (a stage could be skipped), and one pull request per feature regardless of size. The brief skill's slice limit, about 300 changed lines the maintainer reads, exists so that "every pull request the lane opens is one the maintainer can review whole".

## The episode

The chain's first real run changed it the next day. `7d91d25` (2026-10-27), "the feature lane after its first run", records what it taught. A decision on a review finding now resumes the run as a **ruling**, so finished stages replay from cache; amending the brief would change its hash and rerun everything. The same commit added per-phase token counts, the one-screen card, and Your review.

A week later, `ac83be3` (2026-11-03) made the chain fail closed. It now stops on a changed brief, a dead test writer or verifier, a gate whose reported checks did not all pass, an unknown ruling, or a finding in the re-review of the fixes. In the header's words: "an agent's own 'passed' is never trusted over the results it reports."

## Look at

- [`README.md`, "Built with Claude Code + community skills"](../../README.md#built-with-claude-code--community-skills): the outside skill packs several of these pieces were lifted from, idea by idea.
- [`CLAUDE.md`](../../CLAUDE.md), "Working lanes".
- [`.claude/workflows/feature-chain.js`](../../.claude/workflows/feature-chain.js): the build order and its stop rules.
- [`.claude/skills/feature-brief/SKILL.md`](../../.claude/skills/feature-brief/SKILL.md), [`.claude/skills/feature-chain/SKILL.md`](../../.claude/skills/feature-chain/SKILL.md), [`.claude/skills/gate-block/SKILL.md`](../../.claude/skills/gate-block/SKILL.md).
- [`docs/routines/README.md`](../../docs/routines/README.md): the unattended lane.
- `8bff87d`: the feature-chain workflow.
- `60137a9`, `ba8fd97`: routine templates; the private lane dropped.
- `0e1c980`: Ship, Show or Ask.
- `7d91d25`: rulings, cards and Your review after the first run.
- `ac83be3`: the chain fails closed.
- `ec0b073`: gates come out one bite at a time.
