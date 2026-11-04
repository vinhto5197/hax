import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from apps.api.routers.auth import router as auth_router
from apps.api.routers.chat import router as chat_router
from apps.api.routers.conversations import router as conversations_router
from apps.api.routers.documents import router as documents_router
from apps.api.routers.internal_auth import router as internal_auth_router
from apps.api.routers.profile import router as profile_router
from apps.api.turns import drain_turns
from apps.api.watchdog import SlowRequestWatchdog, route_label
from packages.db.session import assert_rls_bound_role


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed at boot rather than serve every request as a role that
    # silently bypasses RLS.
    await assert_rls_bound_role()
    yield
    # Uvicorn reaches this only after its graceful-shutdown timeout has cut
    # open listeners (compose.prod.yml); 1 s for that plus this 8 s drain fit
    # inside compose's 10 s stop window. A turn still running after the drain
    # is cancelled: it stores nothing and releases its claim.
    await drain_turns(8)


# Application logs go to stdout; the environment (terminal, docker logs, a log
# shipper) decides where they land. Level from env so prod stays at INFO.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(lifespan=lifespan)

logger = logging.getLogger(__name__)


# FastAPI's default 422 echoes the rejected body in each error's `input` (a
# bad sign-up sends the password back) and copies input into `ctx`. Only
# loc, msg and type leave the server: the web's 422 mapping
# (apps/web/lib/chatApi.ts) reads loc and msg.
@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError):
    detail = [
        {"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})


# lock_not_available (the app's lock_timeout) and query_canceled (its
# statement_timeout, packages/db/session.py): the request lost to contention
# or load, not to a bug, so it is retryable. The body is fixed text; the log
# carries the route pattern and SQLSTATE only, never the SQL, its parameters
# or the driver's message. Every other database error is re-raised to the default
# 500. The request's session has already rolled back by the time this runs:
# get_session's `async with` exits on the exception before the handler.
_BUSY_SQLSTATES = frozenset({"55P03", "57014"})


@app.exception_handler(DBAPIError)
async def _database_busy(request: Request, exc: DBAPIError):
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate not in _BUSY_SQLSTATES:
        raise exc
    logger.warning(
        "database busy: %s sqlstate=%s", route_label(request.scope), sqlstate
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "The server is busy right now. Try again in a moment."},
        headers={"Retry-After": "5"},
    )


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

# Added last, so it is outermost and times every request, CORS included.
app.add_middleware(SlowRequestWatchdog)

# /api prefix lets the reverse proxy route by path without colliding with
# Next's pages (Next's /chat page vs this /api/chat endpoint).
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(profile_router, prefix="/api")
# No /api prefix: /internal/* is never publicly proxied and is secret-gated
# regardless.
app.include_router(internal_auth_router)


# Under /api so Caddy routes it: the external uptime check and the compose
# healthcheck hit the same path.
@app.get("/api/health")
def health():
    return {"status": "ok"}
