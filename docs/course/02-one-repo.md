# 02. One repo: services and shared libraries

Threads: B (full-stack engineering)

## The idea

A product like hax is several programs at once. One draws the web pages. One answers the browser's requests. One does slow jobs in the background. They need to share some code: the shape of a message, how to talk to the database, how to call the model.

A monorepo (one git repository that holds every part of a project) keeps them together, so one change can touch the API and the web page that uses it in a single commit. The risk is a tangle, where any part reaches into any other and nothing can change alone.

A kitchen is a fair picture. The cooks at each station are the services: each one works on its own. The pantry is the shared libraries: every station takes from it. Stations do not take ingredients from each other's counters. If two stations need the same sauce, it goes in the pantry.

## How hax does it

The repo has two top-level groups:

- [`apps/`](../../apps/) holds runnable services, one process each. [`apps/web`](../../apps/web/) is the Next.js web app. [`apps/api`](../../apps/api/) is the FastAPI server. [`apps/worker`](../../apps/worker/) is the Celery worker that runs background jobs.
- [`packages/`](../../packages/) holds shared Python libraries that are imported, never run. [`packages/core`](../../packages/core/) is the product's logic: the agent loop and its tools, search over documents, auth helpers, email and the data shapes the API sends and receives. [`packages/db`](../../packages/db/) is the database layer: the connection, the table models, the migrations (scripts that change the database's tables one step at a time), and the repos (functions that run each query for one user).

Both Python services import from `packages/`. The worker's ingestion task calls the chunk, embed and store code in [`packages/core/rag/ingest.py`](../../packages/core/rag/ingest.py); the API's chat route ([`apps/api/routers/chat.py`](../../apps/api/routers/chat.py)) calls the agent loop in [`packages/core/agent/harness.py`](../../packages/core/agent/harness.py). Neither copies the other.

The web app is TypeScript, so it cannot import Python code. It shares with the API in a different way. The API's routes produce an OpenAPI spec (a machine-readable description of every endpoint and its fields). `make types` exports that spec and runs openapi-typescript, which turns it into TypeScript types in [`apps/web/lib/openapi.ts`](../../apps/web/lib/openapi.ts). That file is committed, and CI (continuous integration: checks that run on every push) regenerates it and fails if it differs, so the web app cannot drift from the API without the build saying so.

The layout also shapes the deploy. [`infra/docker/python.Dockerfile`](../../infra/docker/python.Dockerfile) copies `apps/api`, `apps/worker` and `packages` into one image (a packaged snapshot of a program and everything it needs to run), and leaves `apps/web` out so a web-only change does not rebuild it. In [`infra/compose/compose.prod.yml`](../../infra/compose/compose.prod.yml) that one image runs as the API, both workers and the migration step, each with its own command. The web app gets its own image.

## What was decided, and why

[ADR 0003](../adr/0003-monorepo-apps-and-packages.md), dated 2026-05-21, records the layout and one rule: services in `apps/` import from `packages/`, and services never import from each other.

It weighed four other layouts:

- **A repo per service.** Better isolation, but every shared change becomes several pull requests (proposed changes, reviewed before they merge) and version bumps (new numbered releases of a shared library). Too much coordination for a small project.
- **One flat repo** with `web/`, `api/`, `worker/` and `core/` side by side. It works, but it loses the line between what runs and what is imported, and it invites one service to import another, which hides coupling.
- **`backend/` and `frontend/`.** Fine when the code splits cleanly by language, but shared pieces such as the generated TypeScript types belong to neither side.
- **A single `src/` folder,** the common Python layout. It does not stretch to several services plus a frontend.

The ADR accepts some costs: overhead while only one service existed, longer import paths such as `packages.core...`, and setup work so the editable install (installing the project so Python imports it straight from its source folders) finds the packages. Python's namespace packages (folders treated as packages without an `__init__.py` file) handled the last one, and `092fdad` deleted the docstring-only `__init__.py` files. It kept `packages/db/__init__.py`, which re-exports names other code imports.

The ADR was written after the code. `apps/` appeared on 2026-02-10, when the Next.js app was added (`f5e232e`) and moved into `apps/web` (`8fc445c`). `packages/` and `infra/` followed in `f528d38` on 2026-02-17. The ADR came in `9582576`, whose message calls the first five ADRs "the load-bearing choices already in the code."

## The episode

The rule says services never import each other, but the API does import from the worker. [`apps/api/routers/documents.py`](../../apps/api/routers/documents.py) imports `ingest_document` from `apps.worker.tasks`; the chat service imports `generate_title`, and the auth routes import `send_email`, from the same module.

This began with the first background job. `68d987f` (2026-07-01) moved ingestion into a Celery worker, and the upload route started queuing the task by calling it from the worker's module. In Celery the object that defines a task is also the handle you use to queue it, so importing the task was the short way to queue it. Titles (`9252c01`) and email (`5f92a75`) followed the same path.

The import is narrower than it looks. The API never runs these functions; it only hands them to [`apps/api/enqueue.py`](../../apps/api/enqueue.py), which puts a message on the queue from a separate thread, and the worker process does the work. The coupling is real all the same: the API cannot load its routes unless the worker's task module loads too, so the two services must always ship together, as they do in the one Python image. For months the exception lived only in the code; a 2026-11-06 addendum to ADR 0003 finally recorded it, allowing these imports only for enqueueing, with the deploy's import check as the guard.

The lesson: a layout rule kept "by convention" holds only as far as people check it. The ADR itself says the rule could be enforced later by linter rules (automatic checks run over the code); v0 has none, and the one exception came in through the easiest path the framework offered.

## Look at

- [ADR 0003](../adr/0003-monorepo-apps-and-packages.md): the layout, the rule, the alternatives
- [`../../apps/`](../../apps/) and [`../../packages/`](../../packages/): the two groups
- [`../../infra/docker/python.Dockerfile`](../../infra/docker/python.Dockerfile): one Python image, web left out
- [`../../apps/api/enqueue.py`](../../apps/api/enqueue.py): how the API hands a task to the queue
- [`../../apps/web/lib/openapi.ts`](../../apps/web/lib/openapi.ts): types generated from the API's spec
- `f5e232e`, `8fc445c`: `apps/` first appears with the Next.js app, 2026-02-10
- `f528d38`: `packages/` and `infra/` first appear, 2026-02-17
- `092fdad`: docstring-only `__init__.py` files dropped for namespace packages
- `9582576`: the first five ADRs, written after the code
- `68d987f`: ingestion moves to the Celery worker; the API imports the task
