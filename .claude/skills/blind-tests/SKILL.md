---
name: blind-tests
description: Tests written by a fresh agent from an interface and a behaviour list, never from the implementation, and before it (test-first); every lane, the main lane included
---

# Blind tests

The agent that wrote the code must not write its tests: tests written beside the implementation agree with it, so green proves nothing, and tests written against existing code pin today's bugs as intended behaviour. A fresh agent writes the tests from two inputs only, the public interface and a behaviour list, then the tests run against the real code.

It is test-first with a different author, in every lane: the controller writes the behaviour list, the fresh agent writes the tests, the controller watches them fail, then the code is written until they pass. A pure refactor (no behaviour a user, a caller or a gate depends on changes) writes no new tests: the existing suite is its test, and it still gets the fresh-eyes reviewer.

## Review tiers (main lane)

Every change is placed in one tier before any code or behaviour list is written, and its gate block names the tier (skill `gate-block`, Provenance). The highest tier that applies wins: a pure refactor of auth or pool code is tier 1, writes no new tests, and keeps the adversarial review.

| Tier | When | Treatment |
|---|---|---|
| 1 | touches auth, security, isolation (RLS), concurrency, a pool, the deploy path or infra, a schema or migration, data deletion, a dependency change, or more than one store | blind tests first, one fresh-eyes reviewer, the adversarial review (never automatic: it runs on the maintainer's "go" after a cost preview; in the main lane, once per item over all its bites: skill `gate-block`, Bites) |
| 2 | any other behaviour change | blind tests first, one fresh-eyes reviewer |
| 3 | a pure refactor, comments, docs, test-only or config hygiene with no behaviour change (none of tier 1's surfaces) | one fresh-eyes reviewer; no new tests for product code (a test-only change's tests are written by a fresh agent from a behaviour list) |

A tier-1 change may skip the adversarial review only when the fresh-eyes review already covered that surface's specific risk (named: the guard, the test that pins it, what the reviewer checked); the gate block states the skip and that reason in one line, and the maintainer can overrule it. The feature chain keeps its own review steps (skill `feature-chain`); the routines' PRs are reviewed in the morning digest (skill `morning-digest`).

## Which suite

The suite closest to the user that can observe the behaviour: a Playwright journey (`apps/web/e2e/`, against the e2e stack and its scripted model, `apps/web/e2e/fake-model/server.mjs`, whose prompt prefixes are the only way to script a reply) for anything a browser can observe; a Vitest or pytest unit test for what only a test can stage (a race, an ordering, a mocked boundary). The behaviour list names the suite per line.

## Inputs the controller prepares

- **Interface:** signatures and types, routes with request and response shapes, component props, test selectors. In the feature lane this is the brief's Interface section, frozen; the implementer codes against the same list.
- **Behaviour list:** one line per behaviour, written as what the user or caller observes ("a second turn while a reply is in flight → 409 and nothing persisted"), not as mechanics. Include the failure paths and the boundaries. No approval needed from the maintainer: a wrong line breaks when the tests run.
- **Files to create or extend**, and the existing test files whose style and fixtures the writer may read.

## The prompt's rules

- Do not open the implementation files beyond their exported names and signatures; do not open an existing test of the same unit beyond its fixtures and mocking style.
- Name every test as the behaviour it checks, so the names alone are the contract.
- Do not run installs or builds. Run only the named test files; failures from an implementation still in progress are expected: report them, do not work around them.
- Report every test name, any behaviour that could not be expressed against the interface, and any assumption made about the interface.

## When the tests run

A failure against the real code is one of two things, and the controller sorts it: a product bug (fix the code), or a wrong behaviour line (fix the line and rerun). Tests never adapt to the code; the implementer never bends the interface to make a test pass. A product question goes to the maintainer as a decision.

## After

- **Mutation check, by hand:** for each new test file, break the product code it covers in two or three deliberate ways, confirm the expected test fails each time, restore the file exactly (`cmp` against a backup).
- **One fresh-eyes reviewer** over the whole change (in the main lane, the whole bite), as always. A change that fixes a class of bug asks the reviewer to grep for every other instance of the class, not only the one fixed.
- **The maintainer reads test names and flagged behaviours only**, never bodies. Flag any test that pins a behaviour the controller is unsure is intended (a 404 counted as success, a merged consecutive turn), because a test written against current behaviour locks it in.
