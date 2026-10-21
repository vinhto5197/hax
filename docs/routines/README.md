# Routines

Prompt templates for the overnight Claude Code cloud routines that work the
small-task backlog. The routine's prompt on claude.ai is a copy of a template
with the night's items in place of `{{QUEUE}}` / `{{ITEMS}}`; the routine
never reads these files, so a change here takes effect at the next refill.
The items themselves are never committed: the repo is public, and an item
can describe a weakness before it is fixed.

- `nightly-prompt.md` — the recurring lane: one branch and pull request per
  eligible item, CI as the only gate (up to 3 fix attempts per PR), one
  notification, no connectors. `main` is protected; the routine's GitHub app
  cannot push to it.
- `private-prompt.md` — the one-shot lane for items that touch protected or
  sensitive areas: local commits only, nothing pushed (every branch of a
  public repo is public; `git push` and the GitHub tools are disallowed in
  the routine's config), reviewed after `claude --teleport <session>`.
