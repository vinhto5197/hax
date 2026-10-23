import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers.auth import router as auth_router
from apps.api.routers.chat import router as chat_router
from apps.api.routers.conversations import router as conversations_router
from apps.api.routers.documents import router as documents_router
from apps.api.routers.internal_auth import router as internal_auth_router
from packages.db.session import assert_rls_bound_role


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed at boot rather than serve every request as a role that
    # silently bypasses RLS.
    await assert_rls_bound_role()
    yield


# Application logs go to stdout; the environment (terminal, docker logs, a log
# shipper) decides where they land. Level from env so prod stays at INFO.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

# Read per request, so a test can lower it.
SLOW_REQUEST_MS = 2000


class SlowRequestLog:
    """Logs any request slower than SLOW_REQUEST_MS to produce its response, so
    a hang leaves a trace. Timed to the response start: for the streaming chat
    route that is the SSE headers, not the whole reply. Logs the route's path
    template, never the raw URL, query string, headers or body (ids and user
    data stay out of logs). Plain ASGI rather than BaseHTTPMiddleware, which
    would run the route in another task and re-wrap the SSE stream."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()

        async def timed_send(message):
            if message["type"] == "http.response.start":
                ms = (time.perf_counter() - start) * 1000
                if ms > SLOW_REQUEST_MS:
                    # The router has matched by now; no route is a 404.
                    route = scope.get("route")
                    logger.warning(
                        "slow request: %s %s -> %d in %d ms",
                        scope["method"],
                        getattr(route, "path", "<unmatched>"),
                        message["status"],
                        ms,
                    )
            await send(message)

        await self.app(scope, receive, timed_send)


app = FastAPI(lifespan=lifespan)

# Dev only: the browser talks to FastAPI cross-origin (ADR 0005 — Next's dev
# rewrite buffers SSE). Behind the production reverse proxy web and API share
# one origin, so no CORS middleware is installed and no origin is trusted.
_cors_origins = [o for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.add_middleware(SlowRequestLog)

# /api prefix lets the reverse proxy route by path without colliding with
# Next's pages (Next's /chat page vs this /api/chat endpoint).
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
# No /api prefix: /internal/* is never publicly proxied and is secret-gated
# regardless.
app.include_router(internal_auth_router)


# Under /api so Caddy routes it: the external uptime check and the compose
# healthcheck hit the same path.
@app.get("/api/health")
def health():
    return {"status": "ok"}
