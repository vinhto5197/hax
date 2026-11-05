// Dev: NEXT_PUBLIC_API_URL hits FastAPI directly (Next's dev rewrite buffers
// SSE). Prod: unset — same-origin via the reverse proxy. See ADR 0005.
// Its own module so the auth pages' API calls stay free of next-auth/react.
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";
