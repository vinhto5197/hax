# Architecture Decision Records

This directory holds Architecture Decision Records (ADRs) — short, dated, immutable documents capturing one architectural decision and the reasoning behind it.

## Why ADRs

Codebases drift. Six months from now, you'll look at a piece of architecture and ask "why on earth did we do it this way?" ADRs let past-you tell future-you. They also signal — to teammates, reviewers, hiring managers — that the project is the product of deliberate thinking, not accident.

## Format

Each ADR is a single markdown file: `NNNN-kebab-case-title.md` with a numeric prefix in creation order. Sections:

- **Status** — `proposed`, `accepted`, `deprecated`, `superseded by NNNN`
- **Date** — when accepted
- **Context** — what problem this decision is solving; what constraints exist
- **Decision** — the choice
- **Alternatives considered** — other options + why they were rejected
- **Consequences** — what becomes easier; what becomes harder; what we accept

## Rules

- **One decision per ADR.** Don't bundle.
- **Immutable.** Once accepted, edit only to mark `superseded by`. If the decision changes, write a new ADR that supersedes the old one.
- **Decisions, not aspirations.** ADRs describe choices that are *in the code*, not "we should do X someday."

## Inspired by

[Michael Nygard's original write-up](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) and the conventions at [adr.github.io](https://adr.github.io).

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-use-sse-for-chat-streaming.md) | Use SSE for chat streaming | accepted |
| [0002](0002-anthropic-sdk-not-agent-sdk.md) | Use anthropic SDK directly (not Claude Agent SDK) | accepted |
| [0003](0003-monorepo-apps-and-packages.md) | Monorepo: `apps/` for services, `packages/` for shared libs | accepted |
| [0004](0004-skip-langchain-in-v0-llm-client.md) | Skip LangChain in v0 LLM client | accepted |
| [0005](0005-bypass-next-dev-rewrite-for-sse.md) | Bypass Next dev rewrite for SSE streaming | accepted |
| [0006](0006-async-sqlalchemy-asyncpg-alembic.md) | Async SQLAlchemy + asyncpg + Alembic for persistence | accepted |
