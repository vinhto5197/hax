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
- Production-shaped: the standard web-tier + worker-tier + broker + S3 split —
  one box running all three at first, separate managed services (ECS,
  ElastiCache) when volume earns them.

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

- [0002](0002-anthropic-sdk-not-agent-sdk.md) — "the harness" overhead framing.
- [0006](0006-async-sqlalchemy-asyncpg-alembic.md) — the async-end-to-end stance
  that makes "don't block the web event loop" matter.

## Addendum (2026-09-22): background titles, and how the API publishes

### The third task: `generate_title`

A conversation's title is generated from its **first user message only**, by a
small model (`TITLE_MODEL`, default `claude-haiku-4-5`) in one non-streaming
call whose reply is constrained to a JSON schema (`{"title": string}`), so a
preamble or label has nowhere to go. The payload is two ids as strings
(`conversation_id`, `user_id`); the worker announces the owner for RLS from the
payload and resets it in `finally` (prefork children are long-lived), reads the
message, releases its connection, calls the model, and writes with
`UPDATE … SET title WHERE id = … AND user_id = … AND title IS NULL`. First
writer wins, so at-least-once delivery and duplicate enqueues are harmless, and
`title IS NULL` stays the one meaning of "needs a title" (nothing else is ever
stored there).

Retry classification: 429/5xx, connection and DB/socket errors back off
5/10/20 s (the helper shared with `send_email`) then give up quietly; anything
else — a non-429 4xx, or any other exception — is our bug and is logged (type,
status, conversation id — never the message or the title) with no retry. The **real** retry is structural: the
API enqueues at conversation creation (right after the first user message
commits) and again on every persisted assistant turn while the title is still
NULL. A refusal therefore costs one small call per turn on that conversation;
a counter column was judged not worth a migration at that price.

The sidebar shows a muted italic "Untitled" until the title lands, which is
normally before the first reply ends (the existing end-of-stream refresh picks
it up). Built, reviewed and **dropped** as not worth their cost: a server-side
placeholder (first 60 characters of the first message via a correlated
subquery) and a mid-stream `title` SSE event polled from `event_stream`. If a
live title is ever wanted, the shape is worker → Redis pub/sub → stream, not
polling on the token path. Holding the reply stream open for the title was
rejected outright.

Addendum (2026-09-27): in practice the reply finishes before the title, so
the first conversation reads "Untitled" until the next message. The fix
chosen for M3 is client-side and off the token path: when the stream ends
and the conversation has no title, the browser re-reads it once a second for
at most ten seconds and updates the sidebar. Send is never disabled. The
pub/sub shape stays the answer if a title is ever needed mid-reply.

### The producer side: `apps/api/enqueue.py`

Titles were the first producer on the chat hot path, and measuring
`.delay()` against a dead broker changed the ingestion-era assumption that a
publish is free: with Redis refusing connections it blocked ~19 s (the
result-backend subscription every publish opens), and on an unroutable host
40 s+ (the OS TCP timeout). A publish is a blocking network call made from the
event loop, so that would have frozen the whole API for every user — and the
public auth routes, whose rate limiter deliberately fails open when Redis is
down, would have been an unthrottled way to do it.

Every publish from the API now goes through one module:

- `fire_and_forget(task, *args, log_ref=…)` for work whose loss has its own
  recovery path (titles: the next turn re-enqueues; email: every link has a
  resend). An asyncio task hands the publish to a small dedicated thread pool
  (`ENQUEUE_THREADS`), so neither the request nor the loop waits; a bounded
  backlog (`ENQUEUE_MAX_PENDING`) drops with a log line when the broker is
  down rather than queueing without limit; failures are logged by exception
  type plus the caller-chosen `log_ref` (a conversation id, or a template
  name — never an address).
- `publish(task, *args)` (awaited, off the loop, re-raises) where the caller
  must know: an upload marks its document `failed` if the task could not be
  queued, so `pending` always means a task really exists.
- `retry=False` on every publish (an in-process retry only holds the caller
  against a broker that is already refusing), `ignore_result=True` on every
  task published this way (nobody reads a result; the subscription was most
  of the hang), and a 2 s broker connect timeout in `celery_app` (connect
  only — the worker's blocking pop is untouched). Measured after: ~6 s per
  publish against a dead broker, on one thread, off the request path; about a
  millisecond healthy.
- The pool has its own threads because the default executor also runs
  password hashing and storage I/O; stuck publishes must never starve those.

Contract for callers, unchanged from email: publish only **after** the DB
commit — the worker sees only committed rows.

Consequence recorded in ADR 0011: a broker outage on the auth routes now
yields the uniform 202 (logged), not a 500 that only the mailing branches
could produce.

## Addendum (2026-10-01) — a scheduled task, and the title poll

**Beat.** The worker now starts with an embedded beat (`--beat`, schedule
file in `/tmp`), which publishes `sweep_anonymous_users` daily (ADR 0011
addendum). An embedded beat is correct for exactly one worker; a second
worker needs a single separate beat process or every tick fires once per
worker.

**Titles.** The sidebar learns a new conversation's title by polling the
list from the browser: after the first reply, once a second for at most ten
seconds, until the title appears. This is not the server polling rejected
above (nothing holds the stream or a connection, and the API does no extra
work per token); it is a client refetch bounded in time, and sending is
never blocked.

**Worker loss and the deadline (2026-10-02).** A message whose worker was
killed mid-task (an out-of-memory parse) is acknowledged, not requeued
(`task_reject_on_worker_lost=False`): the same bytes would kill the next
child forever. The broker's "redelivered" mark is not read anywhere — it
means restored, not died — and a restored message (a warm shutdown at a
deploy, or a visibility timeout of ten minutes after a hard kill) simply runs
again, which every task here tolerates. The document a lost worker leaves at
`processing` gets its terminal status from the API instead: listing a user's
documents fails any of theirs still pending or processing after ten minutes,
as the caller, under RLS (a deadline that fires on a live attempt is
harmless: the attempt still writes `ready` over it). The worker's `stop_grace_period` is above
`task_time_limit`, so a deploy waits for in-flight work rather than killing it.

## Addendum (2026-10-06) — two queues, and a per-user upload cap

**The problem.** One queue and one worker served every task. Ingestion runs
for up to five minutes a message; email, titles and the daily sweep run for
seconds. With a batch of uploads queued, every slot held an ingest and a
signup's verification email waited behind them. The same member could also
queue embedding spend without limit.

**Decision: strict lanes.** Tasks are routed by name in `celery_app.py`
(`task_routes`, every task listed): `ingest_document` goes to a queue named
`ingest`; `send_email`, `generate_title` and `sweep_anonymous_users` go to
the default queue, `celery`. Production runs two worker processes from the
same image: `worker` consumes only `ingest` (one child, the 1 GiB memory
fence, the long stop grace), and `worker-fast` consumes only `celery` (one
child, a smaller fence, a short grace) and carries the embedded beat. Neither
worker ever listens on the other's queue, so a parse can never hold up an
email and an ingest can never land in the small container. `make worker`
starts the same two consumers on the laptop. A test pins the route table:
every registered task has an explicit route, so a new task is placed by
choice, not by default.

The default queue keeps its name. A producer that still runs an older route
table during a roll publishes to the default queue; renaming it would strand
those messages on a queue nothing consumes.

Beat moves with the fast worker, the one that stays single; an ingest worker
can be added without a second beat.

**Rejected.** One worker listening on both queues (its slots are shared, so
a queued ingest still delays an email); a queue-order strategy that lets the
ingest worker help with fast work when idle (the idle capacity is tiny at one
host, and the next host makes the question moot — revisit when the worker
tier has more than one box).

**The cap.** `POST /api/documents` spends one slot of the user's hourly and
daily buckets through the existing Redis fixed-window limiter, keyed on the
user id: five accepted uploads an hour, fifteen a day. Only an accepted file
spends a slot (a rejected suffix or size does not); the check runs after
validation and before the row exists, so a refused upload leaves nothing
behind. The limiter fails open when Redis is down, like every limiter in the
API. A refusal is a 429 whose string detail the upload panel already shows.
