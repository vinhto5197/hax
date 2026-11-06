# 00. What hax is, and how to read this

Threads: A (agentic LLM systems) · B (full-stack engineering) · C (building with Claude Code)

## The product

hax is a chat app. You sign in, upload your own files, and ask questions. The answer comes back word by word, like someone typing. When it used your files, the passages it relied on show under the reply as sources. When it is a list of things with the same fields, it shows as a table you can sort, copy or download. A visitor who has no account can try a few turns of a demo on the landing page.

The project's instructions define "good": a direct answer that understands the user's data, a short note on what data it used, and a structured output when that helps. Not goals: perfect agent autonomy, an over-built architecture, full enterprise compliance.

This repo is v0, an open skeleton: the whole slice from chat box to database to cloud, with deliberately simple search. When v0 is done, no more code is added here.

## The stack in plain words

A web app has parts in the browser, parts on a server, and places where data is kept. hax uses these:

- **Next.js and React** draw the pages in the browser. TypeScript (JavaScript with types the compiler checks) is the language.
- **FastAPI**, a Python web framework, is the API: the server the browser calls to send a message or upload a file.
- **The model** is Claude, called through Anthropic's SDK (software development kit: the official library for calling a service). The API runs a small loop that lets the model call tools, such as a search over the user's files or a calculator.
- **SSE** (server-sent events: the server keeps one connection open and sends the reply in pieces) carries the reply to the browser as it is written.
- **Postgres** is the database. **pgvector** is a Postgres add-on that stores embeddings (lists of numbers that capture what a passage means) so the app can find passages close in meaning to a question. **Voyage AI** makes the embeddings.
- **Celery** runs slow jobs, like reading an uploaded file, in a separate worker process. **Redis**, an in-memory store, carries the queue of jobs and holds rate limits.
- **Auth.js** handles sign-in on the web side, and a signed token tells the API who the user is.
- **Docker** packages each service; **Terraform** (code that describes cloud resources) builds the AWS (Amazon Web Services, Amazon's cloud) setup: one server, a managed database, and file storage.

The README has the same list as a table, and an architecture diagram.

## The milestones

The project's instructions list the milestones. The dates below come from git and from the "shipped" notes in those instructions.

A few terms in the table. RAG means retrieval-augmented generation: find relevant passages first, then let the model answer with them. Lint checks are automatic checks for style and common mistakes. Cursor is another AI code editor, which the project used before Claude Code. A design system is one shared set of colors, type and parts, so every screen looks like the same product.

| Milestone | What it delivered | Dates |
|---|---|---|
| Setup | Repo, first scaffolds, lint checks, the move from Cursor to Claude Code | 2026-02-04 to 2026-04-16 |
| M1 Streaming chat | A reply streamed to the browser, saved to Postgres | from 2026-05-14 (`854f00c`) |
| M2 Data + RAG | Memory of earlier turns, file upload, search as a tool the model calls | shipped 2026-07-29 (`1683dd2`) |
| M2.5 Auth + titles | Sign-in, per-user isolation, chat titles made in the background | shipped 2026-09-22 (`74aa0ad`) |
| M3 Live on AWS | One cloud box, managed database, automatic deploys, the public demo | live 2026-09-27, shipped 2026-10-02 (`2a2b642`) |
| M4 Structured outputs + polish | Sources under answers, tables, a design system | shipped 2026-10-13 (`fe93bb2`) |
| M5 Cleanup, hardening, eval | Test suites, review routines, a harness that scores the model | from 2026-10-14; eval shipped 2026-11-05 |

The plan moved as the work went. The first version of the instructions, in `0ff6f52`, had three milestones, with sign-in and titles inside the first. They were deferred to a new M2.5 in `12b48e6`, so the RAG work could go first. In `236e91e` (2026-06-26) a deploy milestone was brought forward, before the polish work, so deploy problems would show up early and every later change would ride a real pipeline. That plan named a larger AWS setup (containers on Fargate, a load balancer, managed Redis). In `e091c16` (2026-06-30) it became one free-tier server pointed at a managed database, managed Redis and file storage, with Fargate deferred. In `32ee513` it shrank again: Redis moved onto the server, and the load balancer, managed Redis, email sending, alarms and the Fargate path moved to a milestone 3.5, each to be added "when it earns its cost".

## Who wrote it

As of `ec0b073`, the repo has 541 commits. 496 of them carry a `Co-Authored-By` line (a line at the end of a commit message that credits a second author) naming Claude, so most of the code was written by an AI assistant working with the maintainer. Most of those lines name a specific model, and the names change over the months; 78 say only "Claude". Thread C is about how that work was run: what the assistant was told, how its work was reviewed, and which rules became code because a written rule was not enough.

## How to read this

Each chapter after this one has the same five parts:

- **The idea**: the concept, in plain words.
- **How hax does it**: what the code does, with file links.
- **What was decided, and why**: the choice, what it beat, the cost, and the ADR. An ADR (architecture decision record) is a short dated file in `docs/adr/` that records one decision. It is stable once the milestone that produced it closes; a later refinement is a dated addendum, and a change of mind is a new ADR that supersedes the old one.
- **The episode**: one thing that went wrong or surprised, told as what happened, with commit ids.
- **Look at**: the files and commits to open next.

A commit id like `0ff6f52` can be read with `git show 0ff6f52`. You do not need to read code to follow along; the links are there to check a claim.

## Look at

- [`../../README.md`](../../README.md): goal, stack table, architecture diagram; [`../dev-setup.md`](../dev-setup.md): running it locally
- [`../../CLAUDE.md`](../../CLAUDE.md): the milestones, "what good means", non-goals
- [`../adr/README.md`](../adr/README.md): the ADR format, rules and index
- `91a7329`: the initial commit, 2026-02-04
- `854f00c`: first streaming chat scaffold, 2026-05-14
- `12b48e6`: milestones reordered; sign-in and titles move to M2.5
- `236e91e`: the deploy milestone brought forward, before polish
- `e091c16`: the deploy plan cut to one free-tier server, managed data, Fargate deferred
- `32ee513`: M3 split into the smallest live stack and its later growth (M3.5)
- `1683dd2`, `74aa0ad`, `2a2b642`, `fe93bb2`: M2 to M4 marked shipped
