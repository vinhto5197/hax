# hax

AI-first product: primary interface is a **chat experience** that answers user questions using the user's own data and context. This repo is **v0** — an open-source skeleton that ships the full vertical slice. When v0 is done, no further code is added here; a private repo forks from it for v1+ (domain agents, advanced UI, proprietary features).

## Goal (v0)

- Chat produces a direct answer grounded in the user's data, a short explanation of what data was used, and structured output (e.g. tables) when helpful.
- User can sign in, provide or connect data, ask questions in chat, and see results in table/structured view.
- Product feels cohesive; we can add data sources, question types, and agent capabilities without rewriting everything.

**Non-goals:** perfect agent autonomy, over-optimized architecture, full enterprise compliance. **Principles:** working software over perfect abstractions; minimal testable vertical slices; treat user data as sensitive.

## Prerequisites

Install these before setup. Versions are minimums.

| Tool           | Version | Notes                                           |
| -------------- | ------- | ----------------------------------------------- |
| Python         | 3.11+   | Via pyenv or Homebrew                           |
| Node.js        | 18+     | Via nvm or Homebrew                             |
| Docker         | 20+     | Docker Desktop, Colima, Rancher, etc.           |
| docker-compose | 2+      | Usually bundled with Docker; Homebrew otherwise |
| Make           | any     | Pre-installed on macOS / Linux                  |
| direnv         | 2+      | Optional, recommended — auto-loads venv + `.env` on `cd` |

## Local Dev Setup

First-time setup (creates venv, installs deps, pre-commit hooks):

```bash
source setup.sh
```

This creates the venv, installs deps, copies `.env.example` to `.env` (if missing), and sets up pre-commit hooks. Defaults work for local dev.

### Loading the environment

`make dev` needs the Python venv active and `.env` exported into your shell — the API reads `ANTHROPIC_API_KEY` / `CLAUDE_CODE_OAUTH_TOKEN` and the web app reads `NEXT_PUBLIC_API_URL` from the environment.

- **Recommended — [direnv](https://direnv.net):** the committed `.envrc` activates the venv and loads `.env` automatically on `cd` into the repo. Install direnv, hook it into your shell, then approve this repo once:

  ```bash
  brew install direnv          # then add: eval "$(direnv hook zsh)"  to ~/.zshrc
  direnv allow                 # approve .envrc (one time)
  ```

- **Without direnv:** run this once per shell before `make dev`:

  ```bash
  source .venv/bin/activate && set -a && source .env && set +a
  ```

Make sure Docker is running before starting services:

```bash
# If using Colima
colima start

# If using Docker Desktop, just open the app
```

Start everything (Postgres, Redis, FastAPI, Next.js):

```bash
make dev
```

Stop all services:

```bash
make dev-stop
```

Other useful commands:

```bash
make infra-logs      # tail Postgres + Redis logs
make infra-clean     # tear down containers AND delete volumes (full reset)
make infra-psql      # open a psql shell against postgres
make infra-redis-cli # open a redis-cli shell against redis
make infra-verify    # run the full end-to-end infra check (see below)
make setup           # re-run setup.sh without sourcing
```

### Verify local infra

After a fresh clone, a Docker version bump, or anything else that touches the data services, run this end-to-end pass to confirm Postgres + Redis are wired up correctly. Stop and diagnose if any step fails.

**Shortcut:** `make infra-verify` runs the equivalent checks non-interactively via [infra/docker-compose/verify.sh](infra/docker-compose/verify.sh). The script uses `docker exec` directly instead of `make infra-psql` / `make infra-redis-cli`, because those open interactive shells (`-it`) which don't work from a script. Same coverage; the breakdown below is the human-friendly form for debugging a specific failure.

1. `make infra-clean` — start from a known-empty state (deletes named volumes).
2. `make infra-up` — bring postgres + redis up in the background.
3. `make infra-ps` — both services should report `(healthy)` (~20s on cold start).
4. `make infra-psql`, then `SELECT * FROM pg_extension WHERE extname='vector';` — expect one row (confirms the M2-bound `vector` extension is loaded). Exit with `\q`.
5. `make infra-redis-cli`, then `PING` — expect `PONG`. Exit with `exit`.
6. Confirm host-side connectivity (this is the URL `apps/api` uses). With `psql` on the host: `psql postgresql://hax:hax@localhost:5432/hax -c '\dx'`. Without `psql`, via the venv: `.venv/bin/python -c "from sqlalchemy import create_engine, text; print(create_engine('postgresql://hax:hax@localhost:5432/hax').connect().execute(text('SELECT 1')).scalar())"` (expect `1`).
7. Volume-persistence check: in `make infra-psql`, run `CREATE TABLE _probe (x int); INSERT INTO _probe VALUES (1);`. Then `make infra-down`, `make infra-up`, `make infra-psql`, `SELECT * FROM _probe;` — expect the row. Clean up with `DROP TABLE _probe;`.
8. `make infra-down` — leave the machine in containers-down, volumes-kept state.

### Database migrations

The Postgres schema is managed by [Alembic](https://alembic.sqlalchemy.org). ORM models live in [packages/db/models/](packages/db/models/); migration scripts in [packages/db/migrations/versions/](packages/db/migrations/versions/). See [ADR 0006](docs/adr/0006-async-sqlalchemy-asyncpg-alembic.md) for why the stack is async (SQLAlchemy 2.0 + asyncpg + Alembic).

Postgres must be up (`make infra-up`) for any of these:

```bash
make migrate                   # apply all pending migrations (idempotent; no-op if at head)
make migration m="add x table" # autogenerate a migration after changing models
make migrate-down              # roll back the most recent migration
```

- **Fresh database:** after `make infra-up`, run `make migrate` once to create the schema. `make dev` does **not** auto-migrate — run `make migrate` yourself after pulling new migrations or starting from an empty volume.
- **`make migrate` is idempotent.** Alembic records applied revisions in an `alembic_version` table and runs only what's pending, so re-running is safe.
- **After changing a model:** run `make migration m="..."`, then **review the generated file** before committing — autogenerate misses some changes (e.g. constraint/type edits) and can emit an empty migration. Apply it with `make migrate`.
- **`make migrate-down`** reverses the schema change and steps the version pointer back one; it does **not** delete the migration file (migrations are version-controlled history — to undo further, write a new migration forward).

## Stack

| Layer     | Tech                                                          |
| --------- | ------------------------------------------------------------- |
| Frontend  | Next.js (SSR + routing), React, TypeScript                    |
| Backend   | FastAPI, LangChain                                            |
| Streaming | SSE (FastAPI `StreamingResponse`) for chat                    |
| Async     | Celery + Redis (broker + cache)                               |
| Data      | Postgres + pgvector (embeddings)                              |
| Types     | OpenAPI spec → generated TypeScript (e.g. openapi-typescript) |
| Infra     | Docker, Docker Compose                                        |
| Deploy    | AWS, provisioned via Terraform                                |

## Build milestones (v0)

1. **Streaming chat** — Next.js + FastAPI + SSE, conversation history in Postgres, basic auth, background chat title generation (Celery + Redis), Docker Compose (Postgres, Redis, all services).
2. **Data + RAG** — User data upload (files), ingestion (chunk → embed → pgvector) via Celery, RAG in chat, conversation memory with user data context.
3. **Structured outputs + polish** — Table/structured view for results, citation/source display, cohesive UI.
4. **AWS deploy** — provision cloud infrastructure with Terraform and deploy all services to AWS.

## Architecture (v0)

```mermaid
graph TB
  subgraph request [Request path]
    Browser
    NextJS[Next.js]
    FastAPI
    Browser -->|HTTP SSE| NextJS
    NextJS -->|fetch| FastAPI
  end
  FastAPI -->|stream chat| LLM[LLM API]
  FastAPI -->|read write| PG["Postgres + pgvector"]
  FastAPI -->|enqueue tasks| Redis
  subgraph background [Background]
    Redis
    CeleryWorker[Celery Worker]
    Redis -->|consume| CeleryWorker
    CeleryWorker -->|title gen embed ingest| LLM
    CeleryWorker -->|write| PG
  end
```

- Chat responses stream (SSE) directly from FastAPI to the browser; they are not queued through Celery.
- Celery + Redis handle background work: title generation, data ingestion, embedding, index rebuilds.
- pgvector lives in Postgres; no separate vector DB.
