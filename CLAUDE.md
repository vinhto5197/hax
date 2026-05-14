# Project context

## One-liner
Build **hax**: an AI-first product where the primary interface is a **chat experience** that answers user questions using the user's own data + context.

## Repo intent
This repo is v0 — an **open-source skeleton** that ships the complete vertical slice. When v0 is done, no more code is added here. A private repo forks from it for v1+ (domain agents, advanced UI, proprietary features).

## Build milestones (v0)

1. **Milestone 1 — Streaming chat**
   - Next.js chat UI + FastAPI backend + SSE streaming
   - Single LLM, no RAG yet
   - Conversation history persisted to Postgres
   - Basic auth / session
   - Background chat title generation (Celery + Redis)
   - Docker Compose: Postgres, Redis, all services

2. **Milestone 2 — Data + RAG**
   - User data upload (files at minimum)
   - Ingestion pipeline: chunking, embedding, store in pgvector (Celery tasks)
   - RAG retrieval wired into chat flow
   - Conversation memory that incorporates user's data context

3. **Milestone 3 — Structured outputs + polish**
   - Table / structured view for results (not only free-form text)
   - Citation/source display (what data the answer used)
   - Cohesive UI — feels like a product, not a demo collection

4. **Milestone 4 — AWS deploy**
   - Provision cloud infrastructure with Terraform
   - Deploy all services to AWS

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
└─ docs/            Project docs (onboarding, runbooks, architecture notes)
```

## Intent notes
- `apps/*` are runnable services (web/api/worker).
- `packages/*` are internal libraries shared across services.
- Redis is the Celery broker AND cache/session store (one service, two roles).
- Chat responses are streamed (SSE) directly from FastAPI — never queued through Celery.
- Celery handles background work: title generation, data ingestion, embedding, index rebuilds.
- pgvector keeps vector search inside Postgres (no extra vector DB service).
- TypeScript types are generated from the FastAPI OpenAPI spec to prevent drift.
- LangChain is used inside `packages/core` but kept behind clean interfaces so it can be swapped.
- The directory structure is a target layout — start flat, extract as complexity demands. Not every directory needs to exist from day one.
