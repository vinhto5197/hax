from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers.chat import router as chat_router
from apps.api.routers.chat_agent_sdk import router as chat_agent_sdk_router
from apps.api.routers.chat_agentic import router as chat_agentic_router
from apps.api.routers.conversations import router as conversations_router
from apps.api.routers.documents import router as documents_router

app = FastAPI()

# Browser talks to FastAPI via Next's dev rewrites (in dev) or the ALB (in
# prod) — never directly cross-origin. CORS is left as a defensive backstop
# for one-off direct calls (curl, tests, etc.).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Namespace all backend routes under /api so the ALB can route on path prefix
# without colliding with Next's pages (e.g., Next's /chat page vs this /api/chat
# endpoint).
app.include_router(chat_router, prefix="/api")
app.include_router(chat_agent_sdk_router, prefix="/api")
app.include_router(chat_agentic_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(documents_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
