# 03. Streaming the reply

Threads: A (agentic LLM systems) · B (full-stack engineering)

## The idea

A language model writes its answer a few words at a time. If the server waits for the whole answer before sending anything, the person stares at a blank screen for several seconds and then gets a wall of text. If the server passes each piece along as it arrives, the answer appears to type itself out. That second experience is called streaming.

It is the difference between a voicemail, which arrives only once fully recorded, and a phone call, which carries the words as they are spoken.

To stream, the server and the browser need an agreed way to keep a connection open and send the reply in parts. hax uses SSE (server-sent events: the server keeps one connection open and writes the reply as a series of small, labeled messages). It runs over plain HTTP (the protocol browsers use to fetch web pages), so ordinary tools can read it.

## How hax does it

The browser sends one POST request (an HTTP request that carries data, here the user's message) to `/api/chat`. The server answers with the content type `text/event-stream` and keeps the connection open.

On the server, which runs FastAPI (a Python library for building web servers), the chat route in [`apps/api/routers/chat.py`](../../apps/api/routers/chat.py) returns `StreamingResponse` (a response whose body is produced bit by bit by a generator function instead of all at once). That generator is `event_stream` in [`apps/api/chat_service.py`](../../apps/api/chat_service.py). Each event is one line starting with `data: `, followed by a blank line that marks where the event ends. The payload is JSON (a standard text format for structured data), because a raw newline inside the model's text would be mistaken for the end of an event. The stream opens with the conversation's id, then carries text pieces, tool-activity notes and sources, and ends with `data: [DONE]`. If the reply fails, it ends with a fixed error code instead.

Two details keep long replies alive. While the model is thinking or a tool is slow, the server sends a comment line, `: keepalive`, every 15 seconds. And the reply itself runs as its own task on the server ([`apps/api/turns.py`](../../apps/api/turns.py)), so a closed tab does not stop it from being saved; the stream only listens to it.

In the browser, [`apps/web/lib/chatApi.ts`](../../apps/web/lib/chatApi.ts) reads the body with `fetch` and `response.body.getReader()`. Network reads do not line up with event boundaries, so it keeps a buffer (a holding area for text received but not yet used), splits on the blank line, and holds back any partial event until the next read completes it. If nothing at all arrives for 45 seconds, it treats the connection as lost, and the chat hook ([`apps/web/hooks/useChat.ts`](../../apps/web/hooks/useChat.ts)) then checks the saved conversation instead of trusting what streamed.

In production, the reverse proxy (the server in front of the app that routes each request to the right service) is Caddy. Its config in [`infra/compose/Caddyfile`](../../infra/compose/Caddyfile) sets `flush_interval -1` on `/api/*`, so the stream is written through as it arrives.

## What was decided, and why

[ADR 0001](../adr/0001-use-sse-for-chat-streaming.md) chose SSE over three alternatives:

- WebSockets (a two-way connection that both sides can write to at any time). More powerful, but the chat only needs one direction. They need an extra handshake, more client code, and behave differently in proxies.
- Long polling (the browser asks again and again for the next piece). More requests and more delay.
- gRPC streaming (a binary protocol built for streaming between services). Strong, but browser support is weaker and it needs its own infrastructure on both ends.

A plain, non-streaming response was rejected outright: it is the blank-screen experience.

The ADR also records why the browser uses `fetch` rather than `EventSource`, the browser's built-in SSE reader: `EventSource` cannot send a POST body, and the user's message has to travel in one. The accepted costs are that the client cannot speak mid-stream (it sends a new request instead) and that some proxies buffer SSE despite hints not to.

That last cost was not hypothetical. [ADR 0005](../adr/0005-bypass-next-dev-rewrite-for-sse.md) records the fix: in development, the browser calls FastAPI directly at an address set by `NEXT_PUBLIC_API_URL`, read in [`apps/web/lib/apiBase.ts`](../../apps/web/lib/apiBase.ts). In production that variable is unset, the URL stays relative, and the reverse proxy routes it. The price is CORS in development (CORS, cross-origin resource sharing: the rules a browser applies when a page calls a server at a different address), which FastAPI turns on only when `CORS_ALLOW_ORIGINS` is set.

## The episode

The first streaming chat, `854f00c`, made development match production by having the Next.js dev server forward `/api/*` to FastAPI (a "rewrite"). Next.js is the framework hax's web pages are built with; its dev server is the local server used while writing code. Streaming worked with `curl -N` (curl is a command-line tool for making web requests; `-N` stops it from holding output back) straight to FastAPI. In the browser, the reply arrived all at once.

Rather than guess, the cause was isolated with a small matrix, recorded in `6511aac` and ADR 0005. Straight to FastAPI with curl: pieces arrived progressively. Browser through the Next rewrite: every piece arrived within about 7 milliseconds of each other, after a delay of about ten seconds. Browser straight to FastAPI: progressive again. Adding the `X-Accel-Buffering: no` header (a header is a labeled line of metadata sent ahead of the response body), a common hint to proxies not to buffer, changed nothing; Next's dev rewrite ignored it.

So the proxy, not the server or the browser, was holding the stream. `6511aac` removed the rewrite entirely instead of leaving it for other endpoints, because any later caller using a relative URL would silently bring the buffering back. The commit message notes the header was a no-op; the route sends only `Cache-Control` and `Connection`. The ADR lists when to revisit: if Next fixes the buffering, or if a production routing layer starts buffering too.

## Look at

- [`docs/adr/0001-use-sse-for-chat-streaming.md`](../adr/0001-use-sse-for-chat-streaming.md): SSE over WebSockets, polling and gRPC; `fetch` over `EventSource`.
- [`docs/adr/0005-bypass-next-dev-rewrite-for-sse.md`](../adr/0005-bypass-next-dev-rewrite-for-sse.md): the buffering matrix and the direct-URL fix.
- [`apps/api/chat_service.py`](../../apps/api/chat_service.py): `sse_event`, `event_stream`, the 15-second keepalive, `SSE_HEADERS`.
- [`apps/api/routers/chat.py`](../../apps/api/routers/chat.py): the route returning `StreamingResponse`.
- [`apps/web/lib/chatApi.ts`](../../apps/web/lib/chatApi.ts): the stream reader, event parser and 45-second silence limit.
- [`apps/web/hooks/useChat.ts`](../../apps/web/hooks/useChat.ts): `pollForOutcome` and `pollForRetry`, which check the saved conversation after a lost stream.
- [`apps/api/turns.py`](../../apps/api/turns.py): the reply as its own server task.
- ADR 0002's 2026-10-27 addendum ([`docs/adr/0002-anthropic-sdk-not-agent-sdk.md`](../adr/0002-anthropic-sdk-not-agent-sdk.md)): the server owns the turn; a closed tab does not stop the save.
- [`apps/web/lib/apiBase.ts`](../../apps/web/lib/apiBase.ts): `NEXT_PUBLIC_API_URL` in dev, relative in prod.
- [`infra/compose/Caddyfile`](../../infra/compose/Caddyfile): `flush_interval -1` for the API.
- `854f00c`: first streaming chat UI, with the dev rewrite.
- `6511aac`: bypass the Next dev rewrite after the isolation matrix.
