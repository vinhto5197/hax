# 21. What v0 teaches

Threads: A (agentic LLM systems) · B (full-stack engineering) · C (building with Claude Code)

## The idea

v0 is the open skeleton: a chat product that answers from a user's own documents, built end to end and live on AWS, after which no more code is added. This page is the short version of the course. Each lesson is one sentence of advice, then where it was learned. The decision records (ADRs) and commits named here are the evidence; the chapters tell the stories.

## Thread A: agentic LLM systems

- **Never let the model carry identity.** Tools learn who the user is from a per-request `ToolContext`, never from arguments the model fills in, so a tricked model still cannot reach another user's data. [ADR 0012](../adr/0012-structural-isolation.md); [ADR 0002](../adr/0002-anthropic-sdk-not-agent-sdk.md), 2026-09-24 addendum. Chapters [8](./08-tools-and-the-loop.md) and [11](./11-keeping-users-apart.md).
- **Assume prompt injection, and close the exit.** Prompt-side defenses, such as telling the model to ignore instructions in documents, only lower the odds; in ADR 0002's words, "none of them can be relied on, because they all ask a model to behave". What holds is structural: only same-origin images and a strict CSP (content security policy: the browser refuses requests to other sites), so a reply cannot leak data with zero clicks. ADR 0002, 2026-09-24 addendum. [Chapter 9](./09-when-the-model-invents.md).
- **Let the harness, not the model, say what was used.** The harness is the loop code that runs the model and its tools. The sources under an answer are the passages the search tool actually returned, recorded by the loop, not citations the model writes. ADR 0002, 2026-10-06 addendum. [Chapter 8](./08-tools-and-the-loop.md).
- **"Nothing found" and "could not look" are different messages.** An outage that returned an empty list made the model tell users their documents lacked the answer (`6c58180`). [Chapter 18](./18-measuring-the-model.md).
- **Judge model changes by flips, not impressions.** Fixed cases, code checks plus a judge model, a committed baseline, and one rerun before a `broke` flip counts, because the same model passes and fails the same case on different runs. [Chapter 18](./18-measuring-the-model.md).
- **Measure before you set a knob.** The distance cutoff stays unset because measured distances for right answers and for off-corpus questions overlap. [Chapter 18](./18-measuring-the-model.md).

## Thread B: full-stack engineering

- **Isolate the failing layer before fixing.** Streaming worked with `curl` and failed in the browser. A four-row test matrix pinned the buffering on Next's dev proxy. [ADR 0005](../adr/0005-bypass-next-dev-rewrite-for-sse.md). [Chapter 3](./03-streaming.md).
- **Put safety in two layers that cannot hide each other.** Every user-scoped query takes a required `user_id`, and Postgres row-level security (a database rule that hides other users' rows from every query) is a fail-closed backstop. [ADR 0012](../adr/0012-structural-isolation.md). [Chapter 11](./11-keeping-users-apart.md).
- **A "free" call is a network call until measured.** Queueing a background job against a dead broker (the queue service, Redis here, that hands jobs to workers) blocked about 19 seconds, which would have frozen the API's event loop (the one thread that serves every request in turn) for every user. One off-loop publisher fixed every producer. [ADR 0010](../adr/0010-celery-for-ingestion.md), 2026-09-22 addendum. [Chapter 7](./07-work-off-the-request.md).
- **Run in production exactly what CI tested.** CI (continuous integration) is the set of checks run on every push. One lock file serves both, and CI fails on anything unpinned. [Chapter 20](./20-rules-that-hold.md).
- **Test the primitives you lean on.** A lock built on `mkdir` broke when the operating system's `mkdir` changed underneath it. [Chapter 20](./20-rules-that-hold.md).
- **Record decisions, and never rewrite an accepted one.** One decision per ADR; a refinement is a dated addendum; a reversal is a new ADR that supersedes the old one; edits in place are only for the milestone that produced it. [`docs/adr/README.md`](../adr/README.md). [Chapter 0](./00-what-hax-is.md).

## Thread C: building with Claude Code

- **The author of the code must not write its tests.** A fresh agent writes them from a behavior list, before the code, and a mutation check tests the tests. [Chapter 16](./16-tests-you-can-trust.md).
- **Review in proportion to risk, and verify the reviewers.** One fresh-eyes reader on every change; a crowd of lens agents, each finding attacked by skeptics, only for tier-1 surfaces such as auth, concurrency and deploy. Comments are reviewed like code. [Chapter 17](./17-reviews-by-agents.md).
- **Prefer a fixed sequence to an agent's judgment of what is next.** The feature chain runs its stages in order, fails closed, and never trusts an agent's own "passed". [Chapter 19](./19-the-factory.md).
- **Spend human judgment at the two ends.** The maintainer approves a design card and reads a gate block; Ship, Show and Ask decide who merges. [Chapter 19](./19-the-factory.md).
- **A public repo changes the process.** Every branch is public, so sensitive work stays out of the unattended lane, and queued items describing weaknesses are never committed. [Chapter 19](./19-the-factory.md).
- **A rule that slips becomes a check.** Hooks, locks and tests replace rules that "rested on recall". [Chapter 20](20-rules-that-hold.md).
- **Review comes before commit, even when the change is right.** A change pushed unreviewed was reverted and re-landed unchanged after review. [Chapter 20](20-rules-that-hold.md).

## Where the working rules live

This course describes only what committed files show. The skills in [`.claude/skills/`](../../.claude/skills/) and [`CLAUDE.md`](../../CLAUDE.md) hold the rules agents follow: lanes, review tiers, the gate block, the eval gate, the comment policy. The committed [`memory_home.sh`](../../.claude/hooks/memory_home.sh) hook shows how Claude Code's memory notes are meant to be used: a memory holds "the why and a pointer", and the rule itself lives in one home, a skill, `CLAUDE.md` or the Makefile. Nothing beyond that is part of this course.

The commit history is part of the record too. Nearly all of v0's commits carry a `Co-Authored-By` trailer (a tagged line at the end of a commit message) naming the Claude model that helped write them (`git log`). Several generations of models appear in turn.

## Look at

- [ADR 0002](../adr/0002-anthropic-sdk-not-agent-sdk.md): addenda 2026-09-24 (injection), 2026-10-06 (sources), 2026-11-04 and 2026-11-05 (the eval).
- [ADR 0005](../adr/0005-bypass-next-dev-rewrite-for-sse.md), [ADR 0010](../adr/0010-celery-for-ingestion.md), [ADR 0012](../adr/0012-structural-isolation.md).
- [`docs/adr/README.md`](../adr/README.md): the rules for ADRs.
- Chapters [0](./00-what-hax-is.md), [3](./03-streaming.md), [7](./07-work-off-the-request.md), [8](./08-tools-and-the-loop.md), [9](./09-when-the-model-invents.md), [11](./11-keeping-users-apart.md), [16](./16-tests-you-can-trust.md), [17](./17-reviews-by-agents.md), [18](./18-measuring-the-model.md), [19](./19-the-factory.md), [20](./20-rules-that-hold.md).
- `6c58180`: a search outage is an error, not an empty search.
- `8c0a4e5`: rules that rested on recall become hooks.
