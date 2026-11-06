# 01. Working with an AI pair: instructions, not prompts

Threads: C (building with Claude Code)

## The idea

An AI coding assistant starts every session knowing nothing about your project. You can explain the project again in each chat message, or you can write the explanation down once, in a file the assistant reads on its own at the start of every session. The first is a prompt. The second is an instruction file.

Think of a colleague who arrives each morning with no memory of yesterday. Retelling the project every morning is slow, and each telling comes out a little different. A brief on their desk is the same every day, and when something changes you edit the brief.

In Claude Code (Anthropic's coding assistant that runs in a terminal and edits a repo), that brief is a file named `CLAUDE.md`. One at the repo root covers the project; one inside a folder adds rules for that folder. Because the files are committed, a change to how the assistant works gets the same history and review as code.

## How hax does it

The root [`CLAUDE.md`](../../CLAUDE.md) opens with a one-line description of the product and the repo's intent, then the milestones, what "good" means, the non-goals and the guiding principles ("Working software > perfect abstractions", "Treat user data as sensitive by default"). Then come the tech stack, the repo layout, and intent notes: a sentence or two each on how a part works and which rule it must keep. For example, chat replies stream straight from the API and never go on the job queue, and agent tools get the user's identity from the server, never from what the model typed.

A second file, [`apps/web/CLAUDE.md`](../../apps/web/CLAUDE.md), applies only to the web app: TypeScript habits for a team learning the language, such as typing the boundaries first and avoiding `any`.

The root file also holds a section that is about the assistant's own output: "Code comments". It says comments serve two readers, future developers and the AI assistant, and allows only two kinds:

- invariants, constraints and reasons the code cannot express, such as safety boundaries, required ordering, deliberate trade-offs and known traps;
- contracts between modules, stated where the modules meet, so a reader can understand a file without reading the rest of the repo.

It forbids tutorials, explanations of language features, milestone or session history, and comments that narrate what the next line visibly does. The web file points back to this policy instead of keeping its own.

The file grew with the project: 85 lines when created; as of `ec0b073`, 219 lines, touched by 60 commits. Later sections on verifying web changes (`45df6cd`) and on lanes of work (`aa5c39f`) return in chapters 16 and 19.

## What was decided, and why

There is no ADR for this choice; the reasoning sits in the commits.

The project started in Cursor, another AI code editor. Its rules lived in `.cursor/rules/` as three files added in `a870cf5`: the project goal, the structure and stack, and the TypeScript guidelines. Each had a small header saying when it applied, either always or only for files that match a pattern such as `apps/web/**/*.tsx`.

On 2026-04-13 the project moved to Claude Code. A short design note came first (`c3f55b7`), and the move itself (`0ff6f52`) followed the same day. It folded the goal and the stack files into the root `CLAUDE.md` and moved the TypeScript rules into `apps/web/CLAUDE.md`. The web-only rule no longer needed a file pattern; its place in the `apps/web` folder now says where it applies. The commit also dropped a Cursor rule about running work from a plan, because a plugin's skills (packaged instructions the assistant loads for a task) now covered it. The design note kept the README and `CLAUDE.md` apart on purpose: the README serves humans, and `CLAUDE.md` serves the agent. The note itself was removed the same day (`c55aa1f`); the commit history keeps it.

The trade-off is upkeep. An instruction file the assistant trusts has to be true, so every change that makes it false must fix it. The history pays that cost often, in "docs" commits that bring `CLAUDE.md` back in line with the code.

## The episode

By July the code carried many comments written while building, and many of them taught: what a library call did, which milestone a line came from, what was planned later. In `dc0eb44` (2026-07-24) one pass went through 23 app and package files, removed that material, and kept a short form of each real constraint. With the two `CLAUDE.md` files it touched, the diff has 232 lines added and 464 removed, 232 fewer in all, and no change in behavior. The same commit added the "Code comments" policy to `CLAUDE.md`.

In the search code, a comment that explained a distance cutoff, its default, its limits and which milestone would tune it became three lines: the cutoff is optional, it only rejects obviously far passages, and real relevance ranking is a reranker's job.

Writing the rule down did not end the problem. New work kept adding comments that explained a mechanism during review. `a41e8a3` trimmed them from the sign-in work, `c12a193` swept the auth, isolation, email and titles code, and `455e56a` fixed comments that later fixes had made untrue. On 2026-11-05, `995d363`, `48b081a` and `11a11eb` took history, tutorials and narration out of the API, worker, shared libraries and tooling. Their messages state how the change was checked: the Python code is "AST-identical", meaning the parsed program is the same and only comments moved. Last, `e8e4f7f` made comments a review item. A reviewer must find the line of code that makes a comment's claim true, or report it, "since no test runs prose."

The lesson: an instruction tells the assistant what to do; only a check catches what it does anyway. Chapter 20 follows other rules down the same path.

## Look at

- [`../../CLAUDE.md`](../../CLAUDE.md): the root instructions; "Code comments" section
- [`../../apps/web/CLAUDE.md`](../../apps/web/CLAUDE.md): web-only TypeScript rules
- [`../../packages/core/rag/retrieval.py`](../../packages/core/rag/retrieval.py): a file the comment pass rewrote
- `a870cf5`: the first Cursor rules, three files
- `c3f55b7`: design note for the move to Claude Code
- `0ff6f52`: Cursor rules become `CLAUDE.md` and `apps/web/CLAUDE.md`
- `dc0eb44`: comment pass across 23 app and package files, and the comment policy
- `a41e8a3`, `c12a193`, `455e56a`: later sweeps
- `995d363`, `48b081a`, `11a11eb`: the sweep checked AST-identical
- `e8e4f7f`: reviewers check what comments claim
