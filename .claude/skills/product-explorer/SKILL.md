---
name: product-explorer
description: A bounded, unattended run that uses the product as a persona in a local browser and files what confused it as candidate backlog items with evidence; never edits code, never touches production
---

# Product explorer

An experiment in the unattended lane: an agent uses the product the way a chosen persona would and records what confused it. Its output is findings with evidence, never code. It is bounded, so its cost is known before it starts, and it runs only against a local stack.

## Preconditions

- The dev stack is up (`make dev`): the web on :3000, the API on :8000, with the real model (the scripted e2e model cannot produce a confusing answer). The product's own model spend is bounded by the turn limit; forty turns on the default model is well under a dollar.
- The Playwright MCP server is available in the session (`.mcp.json`), pointed at localhost only. Production is never a target: the browser allowlist is a guard rail, not a boundary.
- A throwaway account for the run (email and password set in the run's prompt) and one small text fixture to upload (`apps/web/e2e/` has one).

## The run

Dispatch a background general-purpose agent with: the persona file (`persona-seven.md` here is the first), the account and the fixture path, the notes file path `local/explorer/<YYYY-MM-DD>-<persona>.md`, and the bounds:
- `maxTurns`: 40 (the first measurement run uses 10);
- `maxMinutes`: 45;
- abort after three consecutive failed actions (a click that did nothing, a page that did not load);
- screenshots into `local/explorer/<YYYY-MM-DD>-<persona>/`.

The agent writes the notes file as it goes (the file is the memory between its own steps), ends with `## Findings` and `## Did not get to`, and records in a footer the turns used, the minutes used, and whether it stopped on a bound or on completion. It never edits a file outside `local/explorer/`.

## After the run

The morning digest lists the findings. Each becomes one of: a backlog item marked `[R]` when it is small and needs no decision; a candidate for the feature lane (a brief) when it needs a design; or dropped, with the reason kept in the notes file. A finding is never promoted without its screenshot.

## Measure before scheduling

The first run reports its token count beside its findings. Whether the explorer becomes a schedule is decided from the hit rate of promoted findings against that cost, in the Friday retro.

<!-- bounded loop, notes-as-memory and abort-after-repeated-failure after Kun Chen's gnhf -->
