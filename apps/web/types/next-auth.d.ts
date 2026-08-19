import type { DefaultSession } from "next-auth";

// Auth.js ships Session.user as optional with all-optional fields
// (user?: { id?, email?, ... }). Our session callback in auth.ts always sets
// id (the token's sub — the UUID FastAPI scopes every query by) and email,
// so tighten the types to that runtime guarantee: no null-checks at every
// session.user.id read. Intersection keeps the default fields (name, image).
declare module "next-auth" {
  interface Session {
    user: { id: string; email: string } & DefaultSession["user"];
  }
}
