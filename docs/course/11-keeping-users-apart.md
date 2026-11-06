# 11. Keeping users apart

Threads: B (full-stack engineering)

## The idea

Once hax has many users in one database, every query has to stay inside one user's data. The classic bug is quiet: a query forgets its "only this user's rows" filter, and someone can read another person's conversations by guessing an id. The security community calls this BOLA or IDOR (broken object-level authorization: the server checks who you are but not whether the thing you asked for is yours), and ranks it first on OWASP's list of risks for APIs (the endpoints programs call) (OWASP is a nonprofit that publishes web security guidance).

A filter you have to remember is a filter you will one day forget. So hax uses two locks on the same door, each built to hold on its own, and tests that check each lock with the other one removed.

## How hax does it

**Layer one: the repo layer** (repository modules: the one place each table's queries are written). Every conversation and document query lives in [`packages/db/repos/`](../../packages/db/repos/). Each user-scoped function takes `user_id` as a required argument, so a caller cannot write the call without naming the owner. When the row belongs to someone else, the function returns nothing and the route answers 404 (not found), never 403 (forbidden), so the reply does not confirm that the row exists. Document search gets the user's id from a per-request `ToolContext`, never from the model's tool input, so a prompt cannot talk the model into searching someone else's files.

**Layer two: row-level security in Postgres** (the database hax runs on). RLS (row-level security: database rules that hide rows a session may not see) is switched on and forced on `conversations`, `messages`, `documents`, `chunks` and `user_profiles`. "Forced" means the rule applies even to the table's owner. Each policy compares the row's `user_id` with a per-transaction setting, `app.current_user_id` (a transaction is a group of database steps that succeed or fail together). One listener in [`packages/db/session.py`](../../packages/db/session.py) sets it at the start of every transaction from a ContextVar (a Python variable holding a separate value per request or task), defined in [`packages/db/user_context.py`](../../packages/db/user_context.py). The setting is `SET LOCAL`, so it dies when the transaction ends and a pooled connection (one kept open and reused across requests) cannot carry one user's identity into the next request. If nothing announced an identity, the setting is empty and the policies match zero rows, so a forgotten scope fails closed: nothing instead of everything.

**The role split.** Postgres superusers (all-powerful admin roles) skip RLS entirely, so the app must not connect as one. The app connects as `hax_app`, a role with no superuser rights and no right to bypass RLS. The owner role is kept for migrations (the scripts that change the schema) and admin tools.

**The tests prove each layer alone.** [`tests/api/test_repos_scoping.py`](../../tests/api/test_repos_scoping.py) calls the repo functions over a superuser connection, where RLS cannot help, so only the repo's own `WHERE user_id = …` can produce the right answer. [`tests/api/test_rls.py`](../../tests/api/test_rls.py) does the opposite: it runs deliberately unscoped queries as `hax_app` and checks that the database alone partitions them, and that a connection with no identity sees zero rows.

## What was decided, and why

[ADR 0012](../adr/0012-structural-isolation.md) (an architecture decision record: a file recording one decision and why) rejected filter discipline alone (it fails silently by omission), a `SET LOCAL` at each call site (the same omission problem, moved), and a worker role that bypasses RLS (background tasks would then run a different, untested path; instead they carry the user id and announce it like requests do).

Some tables are deliberately outside RLS. `accounts` and `email_tokens` are read by flows that run before anyone signs in, (Google sign-in, clicking an email link), so a policy would refuse exactly the reads they need. Instead, each is queried through one repo module, keyed on a provider identity or a hashed token, never an id the caller picked.

The 2026-11-06 addendum widened the guard. [`tests/api/test_rls_coverage.py`](../../tests/api/test_rls_coverage.py) now reads every table in the public schema (where hax's tables live) from the database catalog (Postgres's own list of its tables and rules) and fails if any is not enabled, forced and covered by at least one policy, unless an `EXEMPT` list names it with a reason. It used to check only tables with a `user_id` column, missing `messages` (owned through its conversation). Two tables joined the exemptions: `users`, which credential checks and every request's revocation check read before an identity exists, and `alembic_version`, the migration ledger, which holds no user rows. The file says adding a table to it "is a decision for ADR 0012, not for this file." A separate test fails if an exempt table no longer exists, so the list cannot rot.

## The episode

The layers arrived separately. `9d3b364` created the least-privilege `hax_app` role and kept the owner role for migrations. Four days later, `de548ed` turned on forced RLS with fail-closed policies; its migration first checks that `hax_app` exists and stops with instructions if not, rather than failing halfway.

Later, the question became the tests. A test that sends a request through the whole app exercises both layers at once. If a repo function had lost its filter, RLS would still return the right rows, and the test would pass for the wrong reason. `43c2aed` closed the remaining gaps: new layer-one tests for `get_owned_detail`, `claim_turn` and `fail_stale` on the RLS-bypassing connection, and search tests that give the second user a real chunk, so the main query's filter is what gets tested rather than an early "no chunks" exit.

## Look at

- [`docs/adr/0012-structural-isolation.md`](../adr/0012-structural-isolation.md) — the two layers, the exemptions, the 2026-11-06 addendum.
- [`packages/db/user_context.py`](../../packages/db/user_context.py) and [`packages/db/session.py`](../../packages/db/session.py) — the ContextVar and the one listener that announces it.
- [`packages/db/migrations/versions/57453c64447d_enable_rls.py`](../../packages/db/migrations/versions/57453c64447d_enable_rls.py) — the policies and the fail-closed comparison.
- [`tests/api/test_repos_scoping.py`](../../tests/api/test_repos_scoping.py) — layer one alone.
- [`tests/api/test_rls.py`](../../tests/api/test_rls.py) — layer two alone.
- [`tests/api/test_rls_coverage.py`](../../tests/api/test_rls_coverage.py) — every public table under forced RLS, or a named exemption.
- `9d3b364` — the least-privilege runtime role.
- `de548ed` — forced RLS on all user-owned tables, fail-closed.
- `43c2aed` — each repo filter and the RLS guard proven on their own.
