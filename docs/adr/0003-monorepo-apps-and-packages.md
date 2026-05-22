# 0003 — Monorepo: `apps/` for services, `packages/` for shared libs

**Status:** accepted
**Date:** 2026-05-21

## Context

The project will eventually consist of multiple runnable services:

- `apps/web` — Next.js frontend (TypeScript)
- `apps/api` — FastAPI backend (Python)
- `apps/worker` — Celery worker (Python, planned for M1 — title generation, ingestion, embeddings)

Each will share code: Pydantic schemas, the LLM client, database session/models. The repo needs a layout that supports both runnable services and shared internal libraries without creating tangled inter-service dependencies.

## Decision

Single monorepo with two top-level groups:

```
apps/        ← runnable services (one process each)
  web/
  api/
  worker/
packages/    ← shared internal libraries (imported, not run)
  core/      ← LLM client, Pydantic schemas, business logic
  db/        ← SQLAlchemy session, ORM models (M1+)
```

**The rule:** services in `apps/*` import from `packages/*`. Services never import from each other.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Separate repos per service** | Higher isolation but high coordination cost: every shared change becomes a multi-repo PR + version bump + bumps in consumer repos. Overkill for a small project; we'd reverse it within months. |
| **Single flat repo** (`web/`, `api/`, `worker/`, `core/`, all at root) | Workable but loses the runnable-vs-library distinction. Encourages services to import from each other (e.g., `from worker.tasks import ...` from inside the api), which creates hidden coupling. |
| **`backend/` + `frontend/` split** | Reasonable for projects strictly siloed by language. Doesn't naturally accommodate cross-cutting shared code (e.g., OpenAPI-generated TypeScript types from FastAPI schemas live in neither). |
| **`src/` flat** (Python convention) | Works for single-package Python projects; doesn't extend to multi-service + frontend repos. |

## Consequences

**Positive:**

- Services and libraries are visually separated; adding a new service is just `mkdir apps/<new>` without restructuring
- The constraint "services never import services" is enforceable via convention and (later) linter rules
- Convention recognized by Nx, Turborepo, pnpm workspaces, Pants, Bazel — if we ever add monorepo tooling, this layout is friction-free
- Each service can be Dockerized independently (one image per service)
- Future: `packages/api-types/` could hold OpenAPI-generated TS types consumed by `apps/web`, bridging language boundaries

**Negative / accepted:**

- Some upfront overhead for a single-service v0. `packages/core/` only has two consumers planned, one currently active.
- Slightly longer import paths (`packages.core.llm.client` vs `core.llm.client`).
- Editable install (`pip install -e .`) needs setuptools to discover packages. Resolved by using Python's native namespace packages (no `__init__.py` required except where re-exports live). See also: this project's pyproject doesn't need `namespaces = true` in editable mode because the project root is on sys.path.

## Related

- [CLAUDE.md](../../CLAUDE.md) documents the same structure as intent; this ADR captures it as a decision.
