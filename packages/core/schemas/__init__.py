"""HTTP contract schemas (FastAPI request/response models -> OpenAPI -> TS types).

Naming convention, by data direction:
- `*Request` / `*In`  = INPUT — request bodies FastAPI parses/validates.
- `*Out`              = OUTPUT — response bodies FastAPI serializes.

Distinct from `packages/core/agent/` tool input models, which are Anthropic
tool-use schemas (model-facing), not HTTP contracts.
"""
