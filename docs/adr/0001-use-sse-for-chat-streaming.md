# 0001 — Use SSE for chat streaming

**Status:** accepted
**Date:** 2026-05-21

## Context

The chat needs to deliver LLM-generated tokens to the browser as they arrive — typewriter-style streaming, not "wait 10 seconds then dump." Multiple wire protocols can support one-way server→client streaming.

The chat's interaction pattern is:

- Client sends a single HTTP POST containing the user's message
- Server streams the assistant's response back over a long-lived connection
- Stream ends when the model finishes; connection closes
- No need for the client to mid-stream send anything back

## Decision

Use **Server-Sent Events (SSE)** — `Content-Type: text/event-stream` responses, each event delimited by `\n\n`, each event payload prefixed with `data: `.

Implementation: FastAPI's `StreamingResponse` wraps an async generator that yields SSE-formatted lines. Browser consumes via `fetch` + `response.body.getReader()` (not `EventSource`, because `EventSource` doesn't support POST request bodies).

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **WebSockets** | Bidirectional + more powerful, but overkill for one-way streaming. Requires HTTP-Upgrade handshake; more complex client code; different proxy/load-balancer behavior. Standard HTTP/SSE composes more naturally with FastAPI and ALB. |
| **Long polling** | Client repeatedly polls for next chunk. Higher latency, more requests, worse server scalability. |
| **`async/await` request returning full response** | No streaming UX. User sees blank screen for 10 seconds, then everything at once. |
| **gRPC streaming** | Best-in-class streaming, but requires gRPC infrastructure on both ends. Browser tooling for gRPC-web is weaker than for HTTP/SSE. Overkill for a single endpoint. |

## Consequences

**Positive:**

- Works with stock HTTP — debuggable via `curl -N`, visible in browser DevTools EventStream tab
- Composes with FastAPI's `StreamingResponse` and async generators (`async def events()` + `yield`)
- AWS ALB and most reverse proxies pass SSE through correctly (with one notable exception — see [0005](0005-bypass-next-dev-rewrite-for-sse.md))
- Same protocol works in dev (FastAPI) and prod (FastAPI behind ALB)

**Negative / accepted:**

- One-directional only. The client cannot send anything mid-stream. Acceptable: chat input is a separate HTTP POST.
- Browsers cap concurrent connections to ~6 per origin. Not a problem for chat (one connection per active chat).
- Some proxies/middlewares (notably Next.js's dev rewrite — see [0005](0005-bypass-next-dev-rewrite-for-sse.md)) buffer SSE despite headers like `X-Accel-Buffering: no`. Mitigated by bypassing them in dev.
