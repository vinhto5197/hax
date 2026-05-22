# 0005 — Bypass Next dev rewrite for SSE streaming

**Status:** accepted
**Date:** 2026-05-21

## Context

The chat frontend (Next.js) and the chat backend (FastAPI) run as separate processes in development — `next dev` on `:3000`, `uvicorn` on `:8000`. The browser is cross-origin to FastAPI in dev but same-origin in prod (where ALB does path-based routing).

Initial design (per [0003](0003-monorepo-apps-and-packages.md) intent) was to make dev mirror prod path-routing via Next's [`rewrites()`](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites):

```ts
// next.config.ts — original plan
async rewrites() {
  return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
}
```

The frontend would `fetch("/api/chat")` (relative URL). In dev, Next's rewrite proxies to FastAPI; in prod, the ALB routes `/api/*` to FastAPI. Same code, no env var, no CORS in either env.

This worked for non-streaming endpoints. For SSE streaming, **Next's dev rewrite buffers the response** — it accumulates all chunks server-side before forwarding to the browser, killing the live-token UX.

Empirical isolation (recorded for future debugging):

- `curl -N` directly to FastAPI: streams chunks progressively over ~10 seconds ✓
- Browser → Next rewrite → FastAPI: all chunks arrive in browser within ~7ms, after a 10-second delay (buffered)
- `X-Accel-Buffering: no` response header: no effect; Next's Turbopack-based dev rewrite ignores it
- Browser → FastAPI direct (cross-origin): streams chunks progressively ✓

## Decision

In dev, the frontend fetches FastAPI **directly via absolute URL**, bypassing Next's dev rewrite:

```ts
// apps/web/lib/chatApi.ts
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
const response = await fetch(`${BASE_URL}/api/chat`, ...);
```

- **Dev:** `.env` sets `NEXT_PUBLIC_API_URL=http://localhost:8000` → fetch hits FastAPI directly. CORS handles cross-origin (FastAPI's `CORSMiddleware` allows `http://localhost:3000`).
- **Prod:** env var unset → `BASE_URL=""` → fetch hits `/api/chat` (relative) → ALB routes to FastAPI.

The Next dev rewrite was **removed** rather than kept as a no-op for the streaming case. There are no other API endpoints today; reintroducing the rewrite (or any proxy) for SSE would silently break streaming again.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Accept the buffered UX in dev** | Streaming is the centerpiece of the product. Dev-time UX matters for iteration speed and demo recording. |
| **Add `X-Accel-Buffering: no` header** | Verified ineffective for Next's dev rewrite. Standard nginx/CloudFront hint; Turbopack ignores it. |
| **Use a custom dev proxy** (http-proxy, nginx in Docker, etc.) | More moving parts. Config drift risk. Doesn't earn its weight for one endpoint. |
| **Switch to WebSockets** | Protocol change for unrelated reasons. See [0001](0001-use-sse-for-chat-streaming.md). |
| **Hit FastAPI server-side from Next API routes** | Forces all chat through a Next.js Node.js intermediary; doesn't solve the buffering problem (Node would also need careful flushing) and adds a hop. |

## Consequences

**Positive:**

- Streaming works in dev with no protocol changes
- Single env var (`NEXT_PUBLIC_API_URL`) controls dev vs prod routing
- Prod path is unchanged (relative URL + ALB)
- No long-running dev proxy to maintain

**Negative / accepted:**

- Dev requires CORS to be configured on FastAPI (`localhost:3000` allowlisted). Already in place.
- Slight env divergence between dev and prod (env var set in one, unset in the other). Documented in `.env.example`.
- If we ever add a non-streaming endpoint, we'll need to decide: also use direct URL (consistent), or re-introduce the rewrite specifically for non-streaming (avoid CORS, dev-prod parity). Current preference: keep using `${BASE_URL}/api/...` for everything, accept CORS in dev.

## When to revisit

- Next.js fixes the dev rewrite SSE buffering (track upstream)
- Production introduces a request-routing layer that also buffers SSE (would need similar mitigation)
- Adding many backend endpoints — the `BASE_URL` prefix becomes repetitive; might create a thin fetch wrapper

## Related

- [0001](0001-use-sse-for-chat-streaming.md) — the streaming protocol this ADR enables in dev
- [0003](0003-monorepo-apps-and-packages.md) — the monorepo structure where this dev/prod parity matters
