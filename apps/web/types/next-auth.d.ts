import type { DefaultSession } from "next-auth";

// auth.ts's session callback always sets id (the token's sub — the UUID
// FastAPI scopes by) and email, so tighten Auth.js's all-optional defaults to
// that guarantee. The intersection keeps its remaining fields.
declare module "next-auth" {
  interface Session {
    user: { id: string; email: string } & DefaultSession["user"];
  }
}
