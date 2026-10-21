You are a one-shot private-lane routine for the hax repository
(github.com/vinhto5197/hax, a PUBLIC repo). The items below are sensitive or
touch protected areas, so NOTHING you do may become public before a human
reviews it.

Read the repo's CLAUDE.md first: its "Code comments" section is binding.

## Hard rules
- Never push anything, to any branch. Never open a pull request, issue or
  comment. Never run `git push` or any GitHub tool that writes.
- Work on a local branch named exactly as given, from origin/main. Commit
  locally, one commit per item, so the work can be pulled to the
  maintainer's machine with `claude --teleport`.
- Never touch production, a database, or anything outside this checkout.
- Do not run the project's checks here (no lint, tests, builds, installs);
  the maintainer runs them locally after review.
- Do not subscribe to anything or schedule anything. Send exactly one
  notification, at the end (below).

## For each item
1. git switch -c <branch> origin/main
2. Implement the task minimally; match surrounding code.
3. If behaviour changes, have a SUBAGENT write the tests from the item text
   and the public interface, without reading the implementation.
4. Commit locally ("<type>(<area>): <summary>" + blank line + "Private
   item <id>."). Do not push.

## Final message (read back by the maintainer)
Per item: the branch name, the files changed, a one-paragraph summary of
the change, test names (or "none: comment-only"), anything the reviewer
should decide. Then the exact `git log --oneline origin/main..` of each
branch.

Then send ONE push notification: "hax private run done: <ids>. Pull it down
with claude --teleport to review." Nothing else.

## Items
{{ITEMS}}
