# 20. Rules that hold

Threads: B (full-stack engineering) · C (building with Claude Code)

## The idea

A rule written in a document holds only as long as someone remembers it. An AI agent starts each session fresh, and even within one session it can lose track of a rule under load. So hax moves rules out of memory and into something that runs: a script that checks, a lock file that pins, a test that fails. This chapter is about that move.

Think of a kitchen that puts a guard on the slicer instead of a sign saying "mind your fingers". The sign is still useful, but the guard is what holds.

## How hax does it

**Hooks.** Claude Code can run a shell script at fixed points: before a tool call, after one, when the user sends a message, or when the assistant tries to finish its turn. hax registers six in [`.claude/settings.json`](../../.claude/settings.json), each with a header comment saying what it guards:

- [`format.sh`](../../.claude/hooks/format.sh) (after a write): formats the file just written with the same formatters the pre-commit check (the checks that run each time a commit is made) uses, so a long line never costs a round trip. It never blocks.
- [`env_guard.sh`](../../.claude/hooks/env_guard.sh) (before a shell command): refuses a command that names a secret env file or prints the loaded environment. The header lists its own known gaps ("quoted paths, globs, recursive grep"), because it is "a guard rail". Deny rules in `settings.json` cover the file-reading tool.
- [`background_waits.sh`](../../.claude/hooks/background_waits.sh) (before a shell command): a command that waits on CI (continuous integration: the checks GitHub runs on every push) or the journey suite must run in the background, so it does not hold up every other answer.
- [`due.sh`](../../.claude/hooks/due.sh) (on each message): says what the day owes, such as the morning digest or the Friday retro, from a file and the clock, "so the rhythm rests on a file instead of the model's memory of it".
- [`review_gate.sh`](../../.claude/hooks/review_gate.sh) (when a turn ends): refuses a hand-off that asks for a review word ("merge", "commit", "approved") without a Your review section.
- [`memory_home.sh`](../../.claude/hooks/memory_home.sh) (after a write): when the assistant writes one of its memory notes, it is reminded that a rule has one home (a skill, `CLAUDE.md` or the Makefile) and that a memory holds "the why and a pointer".

Most hooks share one design choice: "Any failure: silent, exit 0." A broken guard rail must never stop the work.

**Pinned versions.** [`constraints.txt`](../../constraints.txt) pins every Python package at an exact version. CI and the production image both install from it, and [`scripts/check_constraints.sh`](../../scripts/check_constraints.sh) fails CI on any installed package missing from the lock.

**The gate lock.** [`scripts/with-lock.sh`](../../scripts/with-lock.sh) runs one command at a time on shared resources (the test database, the journey stack, the eval stack), so two agents running tests at once queue instead of colliding.

## What was decided, and why

**A rule that slips becomes a check.** Commit `8c0a4e5` (2026-10-27) is titled "two checks for rules that rested on recall". Both the Your review rule and the one-home rule for memory "missed on 2026-10-27 while resting on recall". Both became hooks the same day, "proven live in a fresh session". The [gate-block skill](../../.claude/skills/gate-block/SKILL.md) now says of Your review: "Enforced, not remembered."

**One lock file for CI and production.** On 2026-10-28 two upstream releases turned CI red overnight. `e6998e1` pinned CI's installs. Less than half an hour later `63b826d` went further: the same lock for the production image, both on Python 3.14.8, so "production runs exactly what CI tested". The commit reports 387 Python tests and 54 journeys passing on the pinned versions. Moving to newer versions is now "a deliberate refresh". The trade-off: updates no longer arrive for free.

The same day, `e6998e1` also added a rule to the morning-digest skill: an item guarding against "a failure nobody has seen" is queued only with evidence. A pull request had been built for a failure Next.js already handles.

**Do not trust a primitive you have not tested.** The lock used to rely on `mkdir` being atomic: the first caller to create the directory holds the lock. `988c92f` (2026-10-29) found that the Rust coreutils Ubuntu 26.04 ships as `mkdir` "lets two racing callers both succeed" in 155 of 300 races, so on GitHub's runners the lock's own test saw two holders about half the time. The lock now creates an owner file with `noclobber`, which opens it exclusive-create: 0 of 300 races, and the test passed 20 of 20.

## The episode

On the night of 2026-09-19, an auth change (`064f081`: resend emails, token pre-checks, a redirect for logged-in users) was committed and pushed before its diff was reviewed. The next morning `feb531f` reverted it. Its message says the change "was committed and pushed before the diff was reviewed; the same changes return as working-tree edits for review". That afternoon, after review, `07b2e9d` re-landed it. Its content is identical to the original. Nothing about the code was wrong. The point was that review comes before commit.

The revert and re-land messages name shas that are not in the public history; the subjects and contents match the commits on `main`. The rule is now written in [`CLAUDE.md`](../../CLAUDE.md): "the controller commits on the maintainer's word, never on plan approval". The [implementer agent](../../.claude/agents/implementer.md) goes further and never commits at all.

## Look at

- [`.claude/hooks/`](../../.claude/hooks/): six hooks, each explained in its header.
- [`.claude/settings.json`](../../.claude/settings.json): where hooks and read-deny rules are registered.
- [`scripts/with-lock.sh`](../../scripts/with-lock.sh): the gate lock and why not `mkdir`.
- [`constraints.txt`](../../constraints.txt), [`scripts/check_constraints.sh`](../../scripts/check_constraints.sh).
- `8c0a4e5`: two rules that rested on recall become hooks.
- `e6998e1`: CI installs at pinned versions; "could happen" items need evidence.
- `63b826d`: one lock for CI and the production image.
- `988c92f`: the gate lock stops trusting `mkdir`.
- `064f081`, `feb531f`, `07b2e9d`: committed before review, reverted, re-landed unchanged.
