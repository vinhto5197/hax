from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers.auth import router as auth_router
from apps.api.routers.chat import router as chat_router
from apps.api.routers.conversations import router as conversations_router
from apps.api.routers.documents import router as documents_router
from apps.api.routers.internal_auth import router as internal_auth_router

app = FastAPI()

# CORS is a defensive backstop: normal traffic is same-origin (dev rewrites /
# prod reverse proxy), not cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# /api prefix lets the reverse proxy route by path without colliding with
# Next's pages (Next's /chat page vs this /api/chat endpoint).
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
# No /api prefix: /internal/* is never publicly proxied (M3) and is
# secret-gated regardless.
app.include_router(internal_auth_router)


@app.get("/health")
def health():
    return {"status": "ok"}
