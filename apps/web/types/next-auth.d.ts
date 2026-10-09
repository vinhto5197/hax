import type { DefaultSession } from "next-auth";

// auth.ts's session callback always sets id (the token's sub — the UUID
// FastAPI scopes by), email (null for an anonymous demo visitor, the only
// marker of one) and name (null for a visitor or a nameless account), so
// tighten Auth.js's all-optional defaults to that guarantee. The intersection
// keeps its remaining fields.
declare module "next-auth" {
  interface Session {
    user: {
      id: string;
      email: string | null;
      name: string | null;
    } & DefaultSession["user"];
  }
}
