# Project context

## One-liner
Build **hax**: an AI-first product where the primary interface is a **chat experience** that answers user questions using the user's own data + context.

## Repo intent
This repo is v0 — an **open-source skeleton** that ships the complete vertical slice. When v0 is done, no more code is added here. A private repo forks from it for v1+ (domain agents, advanced UI, proprietary features, and **rigorous/advanced RAG** — hybrid keyword+vector search, rerankers (Voyage ships one), web-search-as-a-tool, eval-driven tuning — over a **dev-curated domain corpus** rather than user uploads). v0 deliberately stays at naive single-vector retrieval; the advanced RAG is where v1's domain value concentrates, so it's tracked here but built there.

## Build milestones (v0)

1. **Milestone 1 — Streaming chat** *(shipped; auth + title generation moved to M2.5)*
   - Next.js chat UI + FastAPI backend + SSE streaming
   - Single LLM, no RAG yet
   - Conversation history persisted to Postgres
   - Docker Compose: Postgres, Redis, all services

2. **Milestone 2 — Data + RAG** *(active)*
   - Conversation memory: replay persisted turns into the LLM prompt (de-amnesia)
   - User data upload (files at minimum)
   - Ingestion pipeline: chunking, embedding (Voyage AI), store in pgvector — sync first, Celery from slice 2
   - RAG retrieval wired into chat flow
   - Slice 3: retrieval becomes a model-invoked tool (simple agent + harness);
     spot-check the agent by hand while building (small corpus + ~10
     question/expected pairs — dev testing, not a deliverable). The **eval
     harness** itself is an M5 deliverable.

2.5. **Milestone 2.5 — Auth + background titles** *(deferred from M1; done after M2)*
   - Basic auth / session; `users` table; conversations + documents scoped to a user
   - Background chat title generation (Celery + Redis — worker exists from M2)

3. **Milestone 3 — AWS deploy + CI/CD** *(brought forward — deploy early, then continuous)*
   - Provision cloud infra with Terraform (ECS Fargate for the streaming
     backend, ALB path-routing `/api/*`, RDS Postgres + pgvector, ElastiCache
     Redis). Streaming rules out Lambda — see the deploy ADR when written.
   - CI/CD pipeline so every later milestone **auto-deploys** — the value of
     CI/CD is a running pipeline, not a one-off deploy.
   - Why here, not last: deploying early surfaces infra issues (SSE-through-ALB,
     secrets, networking) before a big-bang at the end, keeps a live demo URL
     from M3 on, and yields the AWS/CI-CD/observability portfolio narrative.
     M4 + M5 then ride the pipeline.

4. **Milestone 4 — Structured outputs + polish** *(built against live infra, auto-deployed)*
   - Table / structured view for results (not only free-form text)
   - Citation/source display (what data the answer used)
   - Cohesive UI — feels like a product, not a demo collection

5. **Milestone 5 — Cleanup + hardening + eval** *(final pass before v0 is "done")*
   - Test infrastructure: stand up pytest (+ async DB/API fixtures), backfill
     coverage for the chat + RAG paths that were verified by hand during M1/M2
   - **Eval infrastructure**: a measurable harness for RAG/agent quality
     (Q/A dataset → run → score via exact-match or LLM-as-judge) so retrieval
     and agent changes are tuned and regression-checked by **number, not vibes**.
     A minimal eval rides along with M2 slice 3; M5 makes it systematic.
     Rigorous/eval-driven RAG tuning → v1.
   - Drain the remaining dev + QOL backlogs (`local/*BACKLOG*.local.md`)
   - Tighten foot-guns deferred during feature work (input validation, error
     surfaces, anything flagged "fix in cleanup")

## What "good" means for MVP
- The chat reliably produces:
  - a direct answer that understands context of user's data from previous conversations
  - a short explanation of what data it used (high level)
  - a structured output when helpful (table-like results)
- The product feels cohesive (not a collection of demos)
- We can iterate fast: adding new data sources, new question types, and agent capabilities without rewriting everything

## Non-goals
- Perfect agent autonomy or complex multi-agent orchestration
- Over-optimized architecture
- Full enterprise security/compliance (but we still avoid obvious foot-guns like logging secrets)

## Guiding principles
- Working software > perfect abstractions
- Prefer minimal, testable vertical slices
- Treat user data as sensitive by default
# Tech stack
- Frontend: Next.js (SSR + routing) + React + TypeScript
- Backend: FastAPI + LangChain
- Streaming: SSE (FastAPI StreamingResponse) for chat
- Async: Celery (tasks) + Redis (broker + cache)
- Data: Postgres + pgvector (embeddings)
- Embeddings: Voyage AI (Anthropic has no embeddings API) — see ADR 0007
- Types: OpenAPI spec -> generated TypeScript types (openapi-typescript)
- Infra/dev: Docker (+ docker-compose)
- Deploy: AWS, provisioned via Terraform

# Repo structure (MVP)

```
/
├─ apps/
│  ├─ web/          Next.js frontend: chat UI, routing, table/structured outputs
│  ├─ api/          FastAPI: auth, validation, orchestration, responses
│  └─ worker/       Celery worker for async/long-running jobs (broker = Redis)
│
├─ packages/
│  ├─ core/         Shared product brain: LangChain workflows, RAG, schemas
│  └─ db/           Shared Postgres layer: session/engine, models, migrations, repos
│
├─ infra/
│  └─ docker-compose/   Local service orchestration: Postgres, Redis
│
├─ scripts/         Ad-hoc dev utilities (read-mostly; e.g. corpus inspection)
│
└─ docs/            Project docs (onboarding, runbooks, architecture notes)
```

## Intent notes
- `apps/*` are runnable services (web/api/worker).
- `packages/*` are internal libraries shared across services.
- `scripts/*` are standalone, read-mostly dev utilities (e.g. `corpus.py`); not imported by the app.
- Redis is the Celery broker AND cache/session store (one service, two roles).
- Chat responses are streamed (SSE) directly from FastAPI — never queued through Celery.
- Celery handles background work: title generation, data ingestion, embedding, index rebuilds.
- pgvector keeps vector search inside Postgres (no extra vector DB service).
- `packages/db` is the persistence layer: async SQLAlchemy 2.0 over asyncpg, schema managed by Alembic (`make migrate` applies, `make migration m="..."` generates). Models live in `packages/db/models`; no `repos/` layer yet — queries currently sit in `apps/api` (e.g. `chat_service.py`). See ADR 0006.
- TypeScript types are generated from the FastAPI OpenAPI spec to prevent drift.
- LangChain is used inside `packages/core` for **text splitting only** (`langchain-text-splitters`). Embeddings call the **Voyage SDK directly**; retrieval SQL, prompt assembly, and generation stay hand-rolled (ADR 0008 → superseded by 0009).
- The directory structure is a target layout — start flat, extract as complexity demands. Not every directory needs to exist from day one.
