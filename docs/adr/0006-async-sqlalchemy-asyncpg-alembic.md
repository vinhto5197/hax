# 0006 — Async SQLAlchemy + asyncpg + Alembic for persistence

**Status:** accepted
**Date:** 2026-06-08

## Context

Slice 2 introduced conversation persistence: chats and their messages are stored in Postgres so history survives a reload. This is the first code in `packages/db` (per [0003](0003-monorepo-apps-and-packages.md), the shared persistence library used by both `apps/api` and, later, `apps/worker`).

The constraint that shapes the whole decision is that **the stack is async end to end**. FastAPI handles requests on an asyncio event loop, and the chat endpoint streams tokens over SSE ([0001](0001-use-sse-for-chat-streaming.md)) while persisting the user turn before the stream and the assistant turn in the stream's `finally`. Those DB writes happen *inside* async request handlers, concurrently with other in-flight streams.

A blocking database call on that event loop stalls **every** concurrent stream, not just its own request. So the persistence layer's I/O model can't be an afterthought — it has to match the async runtime.

We also wanted typed models (the codebase type-checks), versioned schema changes (not hand-edited SQL), and a schema that leaves room for M2's pgvector tables without rework.

## Decision

Persist with **async SQLAlchemy 2.0 over asyncpg, managed by Alembic**:

1. **Async engine + session** ([`packages/db/session.py`](../../packages/db/session.py)). `create_async_engine` + `async_sessionmaker(expire_on_commit=False)`. `expire_on_commit=False` so an object stays usable after `commit()` without a refresh round-trip — we read `conversation.id` right after persisting the user turn. `session.py` rewrites the `postgresql://` URL to `postgresql+asyncpg://` in one place so `.env`/`DATABASE_URL` stays driver-agnostic.

2. **Typed declarative models** (`DeclarativeBase`, `Mapped[...]`, `mapped_column`). Models are type-checked and double as the single source of schema truth shared across services.

3. **Alembic with the async migration template** ([`packages/db/migrations/env.py`](../../packages/db/migrations/env.py)). `env.py` injects `DATABASE_URL_ASYNC` (so `alembic.ini` hard-codes no URL), imports all models so autogenerate sees them, and runs migrations over the async engine via `connection.run_sync(do_run_migrations)`.

4. **Postgres-native schema conventions.** UUID primary keys defaulted **server-side** (`gen_random_uuid()`), timestamps as `timestamptz` defaulted on the **DB clock** (`now()`, plus `onupdate=now()` for `updated_at`), a `role IN ('user','assistant')` CHECK, an `ON DELETE CASCADE` FK from messages to conversations, and a composite `(conversation_id, created_at)` index for the hot "load a conversation's messages in order" query.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Sync SQLAlchemy + psycopg2** | A blocking DB call on the asyncio loop stalls all concurrent SSE streams, not just the calling request. Defeats the point of an async stack built around streaming. |
| **Raw asyncpg, no ORM** | Hand-written SQL + manual row→object mapping. Quicker to start, but no typed models and no migration autogeneration — schema-drift risk that grows once M2 adds pgvector tables. The ORM's typing + Alembic autogen earn their weight as the schema expands. |
| **`databases`/`encode` or Tortoise ORM** | Smaller ecosystems and weaker migration tooling. SQLAlchemy 2.0 is the de-facto standard with first-class async support, typed models, and Alembic. |
| **Django ORM** | Brings Django; we're on FastAPI. Wrong framework gravity. |
| **Hand-managed schema (SQL files, manual apply)** | No ordered history, no reversible up/down, easy to apply out of order. Alembic gives versioned, reviewable, reversible migrations. |
| **Client-side UUIDs / app-generated timestamps** | Identity and time would depend on which service wrote the row. Letting Postgres own `gen_random_uuid()` and `now()` keeps them consistent regardless of writer (api today, worker later). |

## Consequences

**Positive:**

- DB I/O is non-blocking and consistent with the FastAPI/SSE runtime — concurrent streams don't stall each other on a query.
- Typed models catch schema mistakes at type-check time and give `apps/api` + `apps/worker` one shared schema definition.
- Alembic autogenerate + reversible migrations: schema changes are versioned, diffable, and reviewable in PRs.
- The DB owns identity and timestamps, so rows are consistent no matter which service inserts them.
- **pgvector-ready:** M2 embedding tables slot into the same model + Alembic flow (the local compose already enables the `vector` extension), no persistence-layer rework.

**Negative / accepted:**

- Async adds ceremony: every call is `await`-ed, sessions are async context managers, and `env.py` is the async template (a `run_sync` bridge over a greenlet) rather than the simpler sync one. More surface area to understand.
- asyncpg needs the `+asyncpg` URL scheme; we rewrite it in `session.py` so `.env` stays clean — one small indirection to remember.
- Autogenerate is not authoritative: it misses some changes (e.g. certain constraint/type edits) and emits a "please adjust!" stub. Migrations need human review, not blind acceptance.
- Models must be imported in `env.py` (`from packages.db.models import *`) or autogenerate won't see new tables — an easy-to-forget step when adding a model.

## When to revisit

- **M2 (data + RAG):** add embedding tables/columns via the same Alembic flow; may pull in pgvector's SQLAlchemy types.
- **Production tuning:** revisit connection-pool settings on the async engine (migrations already use `NullPool`; the app engine uses defaults).
- **A sync DB consumer appears** (e.g. a synchronous Celery task): add a sync engine/session alongside rather than blocking the loop. Not needed while the worker is async.

## Related

- [0003](0003-monorepo-apps-and-packages.md) — `packages/` for shared libraries; `packages/db` is the persistence lib this ADR fills in.
- [0001](0001-use-sse-for-chat-streaming.md) — the streaming I/O model this layer must not block.
