from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers.chat import router as chat_router

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


@app.get("/health")
def health():
    return {"status": "ok"}
