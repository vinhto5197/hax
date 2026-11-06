# Project context

## One-liner
Build **hax**: an AI-first product where the primary interface is a **chat experience** that answers user questions using the user's own data + context.

## Repo intent
This repo is v0 — an **open-source skeleton** that ships the complete vertical slice. When v0 is done, no more code is added here; a **private repo forks from it for v1**, the proprietary, domain-specific version. v0 deliberately stays at **naive single-vector retrieval** — the domain value is built in the private fork, not here.

## Build milestones (v0)

1. **Milestone 1 — Streaming chat** *(shipped; auth + title generation moved to M2.5)*
   - Next.js chat UI + FastAPI backend + SSE streaming
   - Single LLM, no RAG yet
   - Conversation history persisted to Postgres
   - Docker Compose: Postgres, Redis, all services

2. **Milestone 2 — Data + RAG** *(shipped 2026-07-29)*
   - Conversation memory: replay persisted turns into the LLM prompt (de-amnesia)
   - User data upload (files at minimum)
   - Ingestion pipeline: chunking, embedding (Voyage AI), store in pgvector
   - RAG retrieval wired into chat flow
   - Slice 3: retrieval became a model-invoked tool — `/api/chat` is now the
     **single, agentic** chat route (hand-rolled tool-use harness; ADR 0002
     addendum).

2.5. **Milestone 2.5 — Auth + background titles** *(shipped 2026-09-22; deferred from M1)*
   - Auth via **NextAuth/Auth.js** (self-hosted, no per-user cost) — email/password
     + Google, sessions, `users` table, FastAPI verifies the NextAuth JWT;
     email verification + password reset; conversations + documents scoped to
     a user, enforced structurally (repo layer + Postgres RLS). ADRs 0011, 0012.
   - Background chat title generation (Celery + Redis — worker exists from M2),
     and one off-loop publisher for every API-side enqueue. ADR 0010 addendum.

3. **Milestone 3 — Live on AWS** *(shipped 2026-10-02; live since 2026-09-27; deploy early, then continuous)*
   - The smallest live stack first: one EC2 box running the compose topology
     (api, worker, web, Redis, Caddy for TLS and single-origin routing),
     managed **RDS Postgres + pgvector**, **S3** for uploads — all provisioned
     with Terraform. No ALB, NAT, ElastiCache or SES yet: at this volume they
     add cost without capability, and each has a config-level upgrade path.
   - CI/CD *(live)*: `.github/workflows/ci.yml` — lint, Pyright, tests, web checks and a
     generated-types drift check on every push; a passing push to `main`
     rolls the box through `infra/deploy/deploy.sh` (OIDC role, no stored
     AWS key). The value of CI/CD is a running pipeline, not a one-off deploy.
   - An **anonymous demo** *(live)*: the landing page is the demo — a few
     turns about hax itself, no account, no tools, then sign up for the full
     product. Anonymity is `users.email IS NULL` and nothing else; a daily
     sweep removes aged visitors. ADR 0011 addendum.
   - Observability, tier one: container logs with size caps, an external
     uptime check on `/api/health` every five minutes with an email alert
     (a free third-party monitor — an alert that lives on the box dies with
     it), and RDS automated backups.
   - Why deploy here, not last: surfaces infra issues (SSE, secrets,
     networking) early and keeps a live URL from M3 on. M4 + M5 ride the
     pipeline. The deploy ADR records every thin choice and its upgrade.

3.5. **Milestone 3.5 — Grow the live stack** *(after M3; each item when it earns its cost)*
   - ALB + ACM + Route 53 when a second box exists; ElastiCache when Redis
     leaves the box; SES after sandbox exit; CloudWatch alarms; the Fargate
     path; a staging environment variable;
     the hardening items deferred from M3 (RDS CA verification, CSP nonce,
     limiter redesign, per-service env files, network split + Redis auth).

4. **Milestone 4 — Structured outputs + polish** *(shipped 2026-10-13; built against live infra, auto-deployed)*
   - Decisions: ADR 0002 (sources), 0010 (queue split, upload cap, conditional
     status writes) and 0011 (model allowlist) addenda; ADR 0014 (design system).
   - Table / structured view for results (not only free-form text) *(shipped)*
   - Citation/source display (what data the answer used) *(shipped)*
   - Cohesive UI — feels like a product, not a demo collection *(shipped)*

5. **Milestone 5 — Cleanup + hardening + eval** *(final pass before v0 is "done")*
   - Test infrastructure: pytest (async fixtures, real-Postgres authz suite),
     Vitest, Playwright journeys, `make coverage`; see README Tests and
     Verifying web changes below. *(shipped)*
   - **Eval infrastructure**: a measurable harness for RAG/agent quality
     (Q/A dataset → run → score via exact-match or LLM-as-judge) so retrieval
     and agent changes are tuned and regression-checked by **number, not vibes**.
     (Rigorous eval-driven tuning is beyond v0 scope.) *(shipped 2026-11-05:
     `make eval` runs `evals/cases.jsonl` through the real agent loop on its
     own stack, graded by code checks and a judge model; flips against a
     baseline, `make eval-compare` between any two runs; never in CI.
     `evals/README.md`, ADR 0002 addenda.)*
   - Drain the remaining dev + QOL backlogs (kept locally, not committed)
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

## Code comments
Comments serve two readers: future devs and the AI pair-assistant working in
this repo. Write prod-level comments only:
- **Invariants, constraints, and WHYs the code cannot express** — safety
  boundaries, required ordering, deliberate trade-offs, known traps.
- **Cross-module contracts, stated at the boundary** ("the worker re-decodes
  from storage", "status events are never persisted") — so a reader, human or
  AI, can grasp a file's purpose without reading the rest of the repo.
- **Never:** tutorials, language-feature explanations, milestone/session
  history, or narration of what the next line visibly does.
## Verifying web changes
- Every behaviour change ships with a test in the suite closest to the user
  that can observe it: a Playwright journey in `apps/web/e2e/` when a
  browser can observe the behaviour (text, attributes, URL, scroll,
  geometry, network, the scripted model's replies); a Vitest or pytest unit
  test when only a test can stage it (a race, an ordering, a mocked
  boundary). A change with neither says why in its PR. The map of
  behaviours to tests is `docs/testing-map.md`.
- Logic: Vitest beside the source (`make test-web`).
- Known behaviour ("after X, Y"): a Playwright journey in `apps/web/e2e/`
  (`make e2e`, gated in CI). A bug found by hand becomes a journey before it
  is fixed; runbooks do not repeat what a journey covers.
- Looking: after a UI change, the assistant drives the changed screen with
  Playwright MCP (`.mcp.json`) on the local dev or e2e stack — desktop and
  phone width, console clean, screenshots in the hand-off. Never production:
  the origin allowlist is a guard rail, not a boundary.
- By hand: new screens' look and feel, real devices, a pass after significant
  deploys.
- Where no browser is available (a cloud sandbox), the hand-off says so;
  CI's journeys are then the gate.
## Working conventions
- Working specs and plans live in `local/` (gitignored). The durable record
  is an ADR in `docs/adr/`: a new decision with trade-offs gets a new ADR
  linked from the ADR README; a reversal supersedes the old ADR's status
  rather than editing it.
- A plan's tasks end with "present"; the controller commits on the
  maintainer's word, never on plan approval.
- Prefer mechanisms in the harness or the tool layer over provider-specific
  request parameters (ADR 0002 addenda).
## Working lanes
- Main: one item at a time with the maintainer; specs and plans in `local/`;
  blind tests first for a behaviour change (skill `blind-tests`), one
  fresh-eyes reviewer on every change, the adversarial review for a tier-1
  change (the three review tiers and the stated-skip rule: skill
  `blind-tests`);
  the item cut into bites, built in parallel where they can be and
  reviewed and committed one at a time, each with its own gate block (skill
  `gate-block`, Bites).
- Feature: a brief (skill `feature-brief`, approved on an artifact) built by
  the `feature-chain` workflow in its own worktree, with blind tests (skill
  `blind-tests`), embedded reviews, evidence and a PR; the approval covers
  that branch's commits and PR, the merge waits for the maintainer.
- Unattended: the nightly routine and the weekly journeys sweep
  (`docs/routines/`), and the weekly explorer run (skill `product-explorer`,
  started by the due hook on Fridays); no decisions, CI as the gate.
- Each day opens with the digest (skill `morning-digest`); the `due` hook
  (`.claude/hooks/due.sh`) names it, and Friday's retro, until each is marked
  done. "BAU" means: do what the hook lists.
# Tech stack
- Frontend: Next.js (SSR + routing) + React + TypeScript + Tailwind v4 (design tokens in `apps/web/app/globals.css`, ADR 0014)
- Backend: FastAPI (LangChain only for text splitting — ADR 0009)
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
│  ├─ core/         Shared product brain: agent harness + tools, RAG, auth, email, schemas
│  └─ db/           Shared Postgres layer: session/engine, models, migrations, repos
│
├─ infra/
│  ├─ compose/      compose.dev.yml (Postgres, Redis, RustFS for S3, Mailpit for local dev), compose.prod.yml (+ the laptop override), Caddyfile
│  ├─ docker/       python.Dockerfile (api, worker, migrate) and web.Dockerfile
│  ├─ terraform/    EC2 box, RDS, S3, IAM, remote state (bootstrap/); rds-bootstrap.sql; runbook
│  └─ deploy/       deploy.sh: build → push to GHCR by sha → roll the box over SSM; runbook
│
├─ evals/           The eval: cases.jsonl, corpus/, runner, checks, judge, report (make eval)
│
├─ scripts/         Ad-hoc dev utilities (read-mostly; e.g. corpus inspection)
│
└─ docs/            ADRs, the behaviour-to-test map, routine prompt templates
```

## Intent notes
- `apps/*` are runnable services (web/api/worker).
- `packages/*` are internal libraries shared across services.
- `scripts/*` are standalone, read-mostly dev utilities (e.g. `corpus.py`); not imported by the app.
- Redis is the Celery broker AND the auth cache — rate-limit buckets and revocation cutoffs (one service, two roles). Sessions themselves are stateless JWTs, not Redis rows.
- Chat responses are streamed (SSE) directly from FastAPI — never queued through Celery.
- Celery handles background work — five tasks today: `generate_title`, `ingest_document` (chunk → embed → store; every status write is conditional, so `failed` and `ready` are terminal — the listing fails rows stuck `processing` past 10 minutes or `pending` past 6 hours), `send_email`, `sweep_anonymous_users` (daily, from the fast worker's embedded beat; deletes demo visitors older than `ANON_RETENTION_DAYS` (default 3) with everything they own), and `sweep_email_tokens` (daily at 04:30 UTC, from the same beat; deletes email-link rows that are spent, voided or expired, by the database clock). Two queues, routed by task name in `apps/worker/celery_app.py` and consumed by two worker processes that never share a queue: `ingest` (the `worker` service: one slot, 1 GiB fence) and the default `celery` for email/titles/sweeps (`worker-fast`: carries beat). A new task must be given a route — a test fails otherwise. ADR 0010 addendum.
- Uploads are capped per user through the Redis limiter (`packages/core/auth/rate_limit.py`): 5 accepted files an hour, 15 a day, keyed on the user id, checked after validation and before the row exists; 429 with a string detail. Fail-open like every limiter.
- Conversation titles: `generate_title` (worker) titles a conversation from its first user message only, with a conditional `UPDATE … WHERE title IS NULL` (first writer wins; nothing else is ever stored in `title`). The API enqueues at conversation creation and re-enqueues on each persisted assistant turn while untitled — that re-enqueue is the retry. The sidebar shows "Untitled" until then. See ADR 0010 addendum.
- Every Celery publish from the API goes through `apps/api/enqueue.py` (off the event loop, after the DB commit, `retry=False`; `fire_and_forget` for work with its own recovery path — titles, email — and awaited `publish` where the caller must know, e.g. uploads marking a document failed). Every task ignores its result (`task_ignore_result`, the default in `apps/worker/celery_app.py`).
- Transactional email goes through the Celery `send_email` task (`packages/core/email/`: templates + smtplib transport); dev sends to Mailpit (compose, inbox at :8025), prod to a real relay via the same `SMTP_*` env. Emails are enqueued only after the DB commit.
- pgvector keeps vector search inside Postgres (no extra vector DB service).
- `packages/db` is the persistence layer: async SQLAlchemy 2.0 over asyncpg, schema managed by Alembic (`make migrate` applies, `make migration m="..."` generates). Models live in `packages/db/models`; user-scoped queries live in `packages/db/repos/` (required `user_id`; ownership miss → 404). See ADR 0006/0012.
- TypeScript types are generated from the FastAPI OpenAPI spec to prevent drift.
- LangChain is used inside `packages/core` for **text splitting only** (`langchain-text-splitters`). Embeddings call the **Voyage SDK directly**; retrieval SQL, prompt assembly, and generation stay hand-rolled (ADR 0008 → superseded by 0009).
- Chat is **agentic**: `/api/chat` (the only chat route) runs a hand-rolled tool-use loop on the anthropic SDK — `packages/core/agent/harness.py` (loop, MAX_ITERS + no-tools fallback, moving prompt-cache breakpoint) over a registry of four tools in `tools.py` (`search_documents`, `calculator`, `get_current_datetime`, mocked `send_email`). Retrieval is model-invoked, never injected. The harness yields three event kinds — content, status, and sources (the passages a search found, persisted on the assistant message for the client and never replayed to the model). One reply at a time per conversation: the user turn claims `conversations.streaming_since` (409 while a live claim exists; stale after 2 minutes), the reply's save releases it, before `[DONE]`. See ADR 0002 addenda.
- Auth is **NextAuth/Auth.js v5** (web front door, `/auth/*`) + FastAPI identity endpoints (`/api/auth/*` public; `/internal/auth/*` secret-gated: verify-credentials, oauth-upsert, anonymous — Google identities resolve to a hax user there, so JWT `sub` is always a hax id) bridged by a standard HS256 JWT (`packages/core/auth/`); email verification + password reset ride single-use tokens (`packages/db/repos/email_tokens.py`, one live link per purpose) and the gate is ON by default. An anonymous demo visitor is a `users` row with no email and a token with no email — the only marker; `apps/api/demo.py` holds the caps (`DEMO_TURN_LIMIT` as a counter that only goes up, no uploads), and the chat route gives a visitor the guest prompt (`packages/core/demo/prompt.md`) with no tools and the default model; a member's model choice comes from `ChatRequest`'s allowlist. ADR 0011 addendum.
- Isolation is structural: repo layer + Postgres RLS (`FORCE`, GUC `app.current_user_id` announced per-transaction from a ContextVar). The app connects as least-privilege `hax_app`; Alembic uses the owner role via `MIGRATIONS_DATABASE_URL`. Agent tools get identity via `ToolContext`, never model input. See ADR 0012.
- A member's note about themselves (`user_profiles`, one row, ≤ 1000 characters, `GET`/`PUT /api/me/profile`, edited from the account menu's About you dialog) is read before the turn's claim and appended to the agentic system prompt on every turn, behind a fixed preface that frames it as information, never instructions; members only (a visitor gets 403 and never carries a note), never logged.
- Production is `compose.prod.yml` on one EC2 box (Caddy is the only published port; TLS + single origin), RDS Postgres and S3 (instance role, no static keys), Redis on the box — all provisioned by `infra/terraform`. A deploy is `infra/deploy/deploy.sh` at a pushed commit: images tagged by sha on GHCR, compose files fetched at that sha, `/opt/hax/.env` written by hand once and never in the repo or CI. ADR 0013.
- The directory structure is a target layout — start flat, extract as complexity demands. Not every directory needs to exist from day one.
