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

Security-sensitive items, and anything touching auth, migrations, deploy or
CI, are not routine work in this repo: every branch of a public repo is
public, so they are fixed by hand and pushed straight to `main`. (A cloud
session's unpushed commits do not travel with `claude --teleport`, which
moves the conversation only; a private lane would need a private remote.)
