# Routines

Prompt templates for the overnight Claude Code cloud routine that works the
small-task backlog. The routine's prompt on claude.ai is a copy of a template
with the night's items in place of `{{QUEUE}}`; the routine never reads these
files, so a change here takes effect at the next refill. The items themselves
are never committed: the repo is public, and an item can describe a weakness
before it is fixed.

- `nightly-prompt.md` — one branch and pull request per eligible item, CI as
  the only gate (up to 3 fix attempts per PR), one notification, no
  connectors. `main` is protected; the routine's GitHub app cannot push to it.
- `journeys-prompt.md` — fired by hand, not on a schedule: each item is a
  batch of `docs/testing-map.md` rows that becomes one Playwright spec file
  under `apps/web/e2e/` on a `journey/<id>` branch. The sandbox never runs a
  journey, so the prompt carries what the e2e stack can and cannot stage;
  CI's e2e job is the gate, and a journey that finds a product bug is left
  as `test.fixme` with the bug named in the PR, never fixed on that branch.

Security-sensitive items, and anything touching auth, migrations, deploy or
CI, are not routine work in this repo: every branch of a public repo is
public, so they are fixed by hand and pushed straight to `main`. (A cloud
session's unpushed commits do not travel with `claude --teleport`, which
moves the conversation only; a private lane would need a private remote.)

The morning side is a Claude Code session on the maintainer's machine: on
the first message after a date change it lists both routines' runs, reviews
each PR with the diff and CI in front of it, and after the merges refills the
queue (at most ten items, no new PR while ten are open) or pauses the routine
when the queue is empty.
