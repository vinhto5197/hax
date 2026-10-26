---
name: blind-tests
description: Tests written by a fresh agent from an interface and a behaviour list, never from the implementation; for delegated test writing (code written inline follows TDD instead)
---

# Blind tests

The agent that wrote the code must not write its tests: tests written beside the implementation agree with it, so green proves nothing, and tests written against existing code pin today's bugs as intended behaviour. A fresh agent writes the tests from two inputs only, the public interface and a behaviour list, then the tests run against the real code.

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
- **One fresh-eyes reviewer** over the whole change, as always.
- **The maintainer reads test names and flagged behaviours only**, never bodies. Flag any test that pins a behaviour the controller is unsure is intended (a 404 counted as success, a merged consecutive turn), because a test written against current behaviour locks it in.
