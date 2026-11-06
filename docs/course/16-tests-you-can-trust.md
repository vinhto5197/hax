# 16. Tests you can trust

Threads: B (full-stack engineering) · C (building with Claude Code)

## The idea

A test is a small program that runs the real code and checks one thing it should do. A passing test is only worth something if it would fail when the code is wrong. If the same person writes the code and its tests in one sitting, the tests tend to agree with the code, mistakes included. Green then proves only that the code does what the code does.

Think of a student who writes the exam and then grades it. The score is always high. A fairer setup gives the exam to someone who has read only the syllabus. In hax, the "syllabus" is a list of behaviors, and the "someone else" is a fresh AI agent (a separate Claude session with no memory of the work) that has never seen the code.

## How hax does it

The rule lives in a committed skill (a packaged set of instructions that Claude Code loads for a task): [`.claude/skills/blind-tests/SKILL.md`](../../.claude/skills/blind-tests/SKILL.md). It works in this order:

1. The controller (the main Claude session running the work) writes a **behavior list**: one line per thing a user or caller observes, such as "a second turn while a reply is in flight → 409 and nothing persisted" (409 is the HTTP error code for a conflict). Failure paths and edge cases are included.
2. A fresh agent gets only that list and the **interface** (function signatures, routes, component props, test selectors). Its prompt forbids opening the implementation beyond exported names, and asks it to name every test after the behavior it checks, "so the names alone are the contract".
3. The controller watches the new tests fail, then the code is written until they pass. This is test-first with a different author.
4. When a test fails against the real code, it is either a product bug (fix the code) or a wrong behavior line (fix the line). "Tests never adapt to the code."

Tests go in the suite closest to the user that can see the behavior. If a browser can observe it, that means a **Playwright journey**: a script in [`apps/web/e2e/`](../../apps/web/e2e/) that drives a real Chromium browser through the product. If only a test can set it up (a race, an ordering, a mocked boundary), it is a unit test in Vitest (the web app's test runner) or pytest (the Python one). [`CLAUDE.md`](../../CLAUDE.md) states the same rule under "Verifying web changes".

Journeys run against an isolated stack (the full set of running services: database, API, web app). Commit `0bbe8c4` added `make e2e`: it resets its own database and Redis slot (a numbered, separate store inside Redis, the in-memory data store), then starts a scripted stand-in for Anthropic's API ([`apps/web/e2e/fake-model/server.mjs`](../../apps/web/e2e/fake-model/server.mjs)), the API and a production web build. The fake model now answers by prompt prefix: `slow:`, `fail:`, `search:`, `table:` and others, so a journey can stage a failed reply or a table on demand. One day later, `65d262c` ran the journeys in CI (continuous integration: GitHub runs every check on every push) and made the deploy wait for them.

The last piece is [`docs/testing-map.md`](../../docs/testing-map.md): every user-visible behavior of the web app in a table, with the test that would go red if it broke. It started in `81a6a11` with 66 behaviors and 48 gaps. Its counts section now reads 93 behaviors, 91 covered, and 2 gaps, both things a person has to look at (the active row highlight, and fonts with the dark-mode look).

After the tests pass, the skill asks for a **mutation check**, by hand: break the product code in two or three deliberate ways, confirm the test fails each time, then restore the file exactly (`cmp` against a backup). A mutation check tests the test.

## What was decided, and why

- **A different author, not more tests.** The skill's first paragraph gives the reason: tests written beside the implementation agree with it, and tests written against existing code "pin today's bugs as intended behaviour".
- **The maintainer reads test names, never bodies.** The names are the contract, so a person can review a suite in minutes. Any test that locks in behavior the controller is unsure about is flagged for them.
- **A pure refactor writes no new tests.** When nothing a user, caller or gate depends on changes, the existing suite is the test.
- **Rejected:** letting the implementer write its own tests (green proves nothing), and writing tests after the code (they freeze current bugs). The cost: a second agent and a list per change.

There is no ADR for this; it is a working rule, so its home is the skill and `CLAUDE.md`.

## The episode

On 2026-10-14, commit `0c1289c` fixed a small bug: a list of sources with one malformed entry dropped the whole sources footer. The same commit replaced the test suite for the web client's API module, `chatApi.ts`. An agent that had not read `chatApi.ts` rewrote it from a behavior list: 70 tests covering every route and its credentials, a 401 (the HTTP error code for "not signed in") from every call, the download, and the stream contract. The commit message records that the new suite "catches breaks the first suite missed": credentials, the upload field, the download name, and "the eviction re-arm".

The mutation check earns its keep in a smaller way. In `d7b5b86`, a test for the documents panel used one document, so it could not tell "stop polling when every document is ready" from "stop when any is". The rewrite used two documents that finish on different polls, and the message lists three mutations (stop on any, a one-shot timer, a 2-second interval), each of which now fails it.

## Look at

- [`.claude/skills/blind-tests/SKILL.md`](../../.claude/skills/blind-tests/SKILL.md): the protocol, the suite choice, the mutation check.
- [`docs/testing-map.md`](../../docs/testing-map.md): behaviors, what pins each, the gaps.
- [`apps/web/e2e/fake-model/server.mjs`](../../apps/web/e2e/fake-model/server.mjs): the scripted model the journeys talk to.
- `0c1289c`: sources fix; the `chatApi` suite rewritten blind (70 tests).
- `0bbe8c4`: Playwright journeys against an isolated stack.
- `65d262c`: journeys run in CI and gate the deploy.
- `81a6a11`: the behavior-to-test map, 66 behaviors and 48 gaps.
- `d7b5b86`: a poll test strengthened until three mutations fail it.
