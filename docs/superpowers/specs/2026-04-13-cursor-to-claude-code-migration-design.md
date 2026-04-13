# Cursor → Claude Code Migration

## Summary

Migrate all Cursor-specific configuration to Claude Code equivalents. Config/docs migration only — no code, dependency, or structural changes.

## What gets created

### Root `CLAUDE.md`

Auto-loaded every Claude Code session. Content sourced from two Cursor rule files:

**From `project-goal.mdc`:**
- Project one-liner, repo intent, build milestones (v0)
- Definition of "good" for MVP
- Non-goals and guiding principles

**From `project-structure-stack.mdc`:**
- Tech stack (Next.js, FastAPI, LangChain, Celery, Redis, Postgres/pgvector)
- Repo structure with directory purposes and examples
- Intent notes (why it's organized this way)

All Cursor-specific language removed.

### `apps/web/CLAUDE.md`

Scoped to frontend work. Content sourced from `ts-gradual-migration.mdc`:

- Gradual TypeScript guidelines (type boundaries first, inference inside functions)
- `any` avoidance, `unknown` + narrowing preferred
- Type aliases vs interfaces guidance
- JS → TS conversion steps
- Preferred patterns (union types, `Record<string, T>`, `readonly`, React typed props)
- Avoided patterns (heavy generics, advanced conditional types)
- Agent response guidelines (rewritten from Cursor-specific to generic)

## What gets deleted

| Path | Reason |
|------|--------|
| `.cursor/rules/project-goal.mdc` | Migrated to root `CLAUDE.md` |
| `.cursor/rules/project-structure-stack.mdc` | Migrated to root `CLAUDE.md` |
| `.cursor/rules/ts-gradual-migration.mdc` | Migrated to `apps/web/CLAUDE.md` |
| `.cursor/rules/agent-execution-from-plan.mdc` | Superseded by superpowers plugin skills |
| `.cursor/` directory | Empty after rule removal |
| `.prettierignore` | Only existed to ignore `.cursor/` from prettier |

## What's untouched

- `.vscode/` — kept, still used with VS Code
- `.gitignore` — no changes
- `README.md` — no changes (overlap with CLAUDE.md is intentional; README serves humans, CLAUDE.md serves the agent)
- All source code, configs, infra — no changes

## Scope boundary

This is a config/docs migration only. No code changes, no dependency changes, no structural refactoring.
