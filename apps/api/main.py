from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers.chat import router as chat_router
from apps.api.routers.conversations import router as conversations_router
from apps.api.routers.documents import router as documents_router

app = FastAPI()

# CORS is a defensive backstop: normal traffic is same-origin (dev rewrites /
# prod reverse proxy), not cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# /api prefix lets the reverse proxy route by path without colliding with
# Next's pages (Next's /chat page vs this /api/chat endpoint).
app.include_router(chat_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(documents_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
