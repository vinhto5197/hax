# 0012 — Structural per-user isolation (repo layer + RLS)

**Status:** accepted
**Date:** 2026-09-07

## Context

Slice 1 authenticated every request but queries stayed global: any logged-in
user could read, append to, or delete any other user's conversations,
documents, and RAG chunks (BOLA/IDOR — OWASP API #1). Per-query WHERE clauses
were rejected as the primary defense: they fail silently by omission.

## Decision

Two independent layers:

1. **Repo layer** (`packages/db/repos/`): all conversation/document queries
   live here; user-scoped functions take `user_id` as a REQUIRED argument.
   Ownership miss → None → routes answer 404 (never 403 — existence is not
   confirmed). Retrieval (`core/rag/retrieval.py`) requires `user_id`; the
   agent's `search_documents` receives it via a per-request `ToolContext`,
   never as a model-controllable tool parameter.
2. **Postgres RLS** as backstop: ENABLE + FORCE on conversations, messages,
   documents, chunks. Policies compare `user_id` to the transaction-local GUC
   `app.current_user_id` (`messages` via EXISTS on its conversation).
   Identity is announced by ONE engine-level begin listener reading a
   ContextVar (set by `current_user` / the Celery task body) and issuing
   `SET LOCAL` — transaction-scoped, so pooled connections cannot leak
   identity across requests. Unset context → GUC NULL → zero rows: a future
   query that forgets scoping fails closed instead of leaking.

Role split so RLS is real: the app connects as `hax_app`
(NOSUPERUSER/NOBYPASSRLS); `hax` (owner, superuser in dev) is only for
Alembic + admin tooling — superusers bypass RLS entirely, and RDS (M3) has no
superuser, so dev now mirrors prod.

## Alternatives considered

- WHERE-clause discipline only: silent-failure mode; no backstop.
- Per-callsite SET LOCAL: same omission failure mode as WHERE clauses.
- BYPASSRLS worker role: would leave the worker path unexercised; instead
  tasks carry `user_id` in payloads and announce it like requests do.

## Consequences

- Cross-user reads AND writes 404; authz suite (`tests/api/`) locks it in
  against a real Postgres (`hax_test`), CI included.
- Data-touching migrations run as the owner under FORCE RLS — they must
  toggle RLS or announce identity explicitly (documented M3 hand-off).
- Prod bootstrap must replicate init.sql's `ALTER DEFAULT PRIVILEGES`, or a
  table created by a migration after RLS lands leaves `hax_app` without
  access to it.
- `scripts/corpus.py` uses MIGRATIONS_DATABASE_URL for the all-rows view
  (dev: superuser bypass; on RDS the owner is bound by FORCE — caveat
  tracked for M3).
- `accounts` and `email_tokens` also carry `user_id` but are **deliberately
  outside RLS**: their current consumers run without an announced identity —
  `oauth-upsert` (internal-secret-gated, pre-session) and email-token
  verification during signup/password-reset (pre-login by definition).
  Policying them would zero out the exact flows that need to touch rows
  before a session exists. Revisit once slices 3/4 land those access
  patterns and it's clear what identity, if any, is available at that
  point.
- The authz suite proves the two layers **separately, never blended in one
  assertion**: app-level scoping (repo WHERE / `ToolContext.user_id`) is
  exercised against a superuser session so RLS is out of the picture and
  only the app filter can produce the result; RLS is exercised via the app
  role with no identity announced, so only the DB policy can produce the
  (empty) result. A test that mixed the two could pass for the wrong
  reason — e.g. RLS silently covering for a repo function that forgot its
  WHERE clause.

## Related

- [0011](0011-auth-architecture.md) — auth architecture this isolation
  layer builds on.
- `local/specs/2026-07-30-m2.5-auth-titles.md` — Isolation section (full
  design), Threat model.
