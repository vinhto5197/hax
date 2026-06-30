# 0010 — Celery for ingestion (not FastAPI BackgroundTasks)

**Status:** accepted
**Date:** 2026-06-28

## Context

M2 slice 1 ingests documents **inline** in the upload request:
`upload_document` does `await ingest_document(...)` before returning. The client
therefore **waits for the whole chunk → embed → store pipeline** — seconds of
network-bound work, with a risk of hitting load-balancer request timeouts and
losing the work on a client disconnect. Slice 2a moves ingestion **off the
request**. Three options:

1. **Inline (current)** — runs in the request; client waits. Rejected (the
   problem we're fixing).
2. **FastAPI `BackgroundTasks`** — run the work *after* the response, **in the
   same web process**.
3. **Celery + a broker (Redis) + a separate worker process.**

## Decision

Use **Celery** with a **Redis broker** and a **separate worker** (`apps/worker`).
Upload returns immediately at `pending`; the worker runs the pipeline and drives
`processing → ready|failed`.

### Why not BackgroundTasks — the part worth remembering

BackgroundTasks *does* fix the client-facing problem (the response is sent first,
the work runs after — the upload returns fast). And it **can be async** — pass an
`async def` and FastAPI awaits it on the event loop. So it's tempting. But:

- **`async` only *softens* isolation, it doesn't remove it.** The network waits
  (our async Voyage/S3/DB calls) *yield* the event loop, so I/O doesn't block
  request-serving. **But the work still runs *in the web process*, on the same
  event loop** — the CPU-bound stretches (splitting, building chunk objects,
  JSON/SQL serialization, the bits between `await`s) execute on the web
  process's one core per uvicorn worker, competing with request handling under
  load.
- **Retries can be hand-rolled, but durability cannot.** You can wrap the
  background function in a backoff loop. But if the web process **restarts**
  (deploy, crash, OOM) mid-task, the in-flight work and any pending retries are
  **gone** — nothing persists "doc X still needs ingesting." Making retries
  survive a restart requires a **durable queue** holding the task until it's
  done — which *is a broker*. At that point you've reinvented Celery.

So **isolation and retries are the *soft* arguments** (async + a retry loop get
you most of the way). The **irreducible** reasons BackgroundTasks can't meet are:

1. **Durability** — the task lives in Redis, not in a doomed process; it survives
   a web restart. *(The big one.)*
2. **Independent scaling** — scale ingestion workers separately from the web tier
   (a separate ECS service); BackgroundTasks is forever bound to the web process.

Plus two project-specific pulls: the worker is **reused for M2.5 title
generation**, and the async + idempotent task is the **foundation v1's
dev-curated batch ingestion reuses**. And it's the **standard production
topology** — web tier + worker tier + broker maps directly to ECS + ECS +
ElastiCache.

### Object storage (related decision)

The raw uploaded file goes to **object storage** (S3 in prod, **MinIO** in dev),
not a DB column — upload writes the bytes + a `storage_key`; the worker reads by
key. One **boto3** client, endpoint swapped by env (the Postgres↔RDS dev/prod
parity pattern). Chosen for production-fidelity and to enable re-ingestion
without re-upload.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Inline ingestion** (slice 1) | Client waits the full pipeline; LB-timeout + lost-on-disconnect risk. The thing 2a fixes. |
| **FastAPI BackgroundTasks** | Returns fast but stays in the web process: no durability (lost on restart), no separate scaling. `async` softens isolation; hand-rolled retries lack durability without a broker. |
| **A different task queue** (RQ / Dramatiq / arq) | Same architecture; Celery is the most mature/standard, already in the stack (`celery[redis]` in `pyproject`), reused for title-gen, and portfolio-recognizable. arq is async-native (a fair v1 reconsideration) but Celery's prefork + ecosystem win for v0. |

## Consequences

**Positive:**

- Upload is instant (`pending`); ingestion is durable + retried + isolated from
  request-serving; the worker scales independently and is reused for title-gen.
- Production-shaped: maps 1:1 to ECS web + ECS worker + ElastiCache + S3.

**Negative / accepted:**

- More moving parts: a worker process, a broker, object storage, and the
  at-least-once delivery semantics that **require idempotent tasks**
  (delete-then-insert chunks — see the slice-2a spec).
- A sync→async bridge in the task (`asyncio.run(...)` per task; Celery prefork
  is sync). One short-lived event loop per task — acceptable.
- In **dev**, the worker shares the machine's cores with the web process; in
  **prod** they're separate services, so no contention (see below).

## When to revisit

- If the async stack ever wants a fully-async task queue, **arq** is the natural
  re-evaluation (Celery prefork is sync-first).
- If ingestion grows CPU-heavy (local embedding, OCR) the worker tier's sizing
  and the prefork concurrency become real tuning knobs.

## Related

- Slice-2a design: `local/specs/2026-06-28-m2-slice2a-celery-ingestion.md`.
- [0002](0002-anthropic-sdk-not-agent-sdk.md) — "the harness" overhead framing.
- [0006](0006-async-sqlalchemy-asyncpg-alembic.md) — the async-end-to-end stance
  that makes "don't block the web event loop" matter.
