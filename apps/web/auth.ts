import NextAuth, { CredentialsSignin } from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";
import { SignJWT, jwtVerify } from "jose";

// Rate-limiting leaks nothing (unlike 401's anti-enumeration), so it surfaces
// distinctly. `code` rides the Auth.js redirect as ?code=rate_limited and is
// returned to the client as signIn()'s result.code (redirect:false path).
class RateLimit extends CredentialsSignin {
  code = "rate_limited";
}

// The minting half of the JWT bridge. Cross-module contract with
// packages/core/auth/tokens.py (the verifying half): HS256, iss/aud below,
// claims sub/email/iat/exp/jti/auth_time. auth_time is set ONCE at login and
// preserved across re-issues — FastAPI's revocation compares it to
// users.sessions_valid_after, so refreshing must never launder an old login.
const ISSUER = "hax";
const AUDIENCE = "hax-api";
const MAX_AGE_S = 7 * 24 * 60 * 60;

const key = () => new TextEncoder().encode(process.env.AUTH_SECRET);

export const { handlers, auth, signIn, signOut } = NextAuth({
  // /auth, NOT /api/auth: /api/* belongs to FastAPI (one proxy rule at M3).
  basePath: "/auth",
  session: { strategy: "jwt", maxAge: MAX_AGE_S },
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: { email: {}, password: {} },
      async authorize(credentials) {
        const res = await fetch(
          `${process.env.API_INTERNAL_URL}/internal/auth/verify-credentials`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Internal-Secret": process.env.INTERNAL_API_SECRET ?? "",
            },
            body: JSON.stringify({
              email: credentials.email,
              password: credentials.password,
            }),
          },
        );
        // Rate-limited is safe to distinguish (no account-existence leak).
        if (res.status === 429) throw new RateLimit();
        // Any other failure (401/403/500) -> null -> one generic UI message,
        // keeping wrong-password and no-account deliberately indistinguishable.
        if (!res.ok) return null;
        return (await res.json()) as {
          id: string;
          email: string;
          name: string | null;
        };
      },
    }),
    Google,
  ],
  callbacks: {
    async signIn({ user, account, profile }) {
      // Credentials sign-ins were already decided by authorize().
      if (account?.provider !== "google") return true;
      // FastAPI owns identity: it applies the linking rules and returns the
      // hax user (ADR 0011). A refusal or outage must land the user back on
      // /login with a message, so failures become redirect URLs, not throws.
      // Everything that can throw (the fetch, and parsing a 200 body that
      // turns out to be malformed) stays inside this try — any failure here
      // must become a redirect string, never an uncaught throw, or Auth.js
      // sends the user to its own /auth/error page instead of ours.
      let hax: { id: string; email: string; name: string | null };
      try {
        const res = await fetch(
          `${process.env.API_INTERNAL_URL}/internal/auth/oauth-upsert`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Internal-Secret": process.env.INTERNAL_API_SECRET ?? "",
            },
            body: JSON.stringify({
              provider: "google",
              provider_account_id: account.providerAccountId,
              email: profile?.email,
              email_verified: profile?.email_verified === true,
              name: profile?.name ?? null,
            }),
          },
        );
        if (res.status === 403) return "/login?error=google_unverified";
        if (!res.ok) return "/login?error=google_failed";
        hax = (await res.json()) as typeof hax;
      } catch {
        return "/login?error=google_failed";
      }
      if (typeof hax?.id !== "string") return "/login?error=google_failed";
      // Without a database adapter Auth.js passes this same object on to the
      // jwt callback, which reads user.id into token.sub — so the JWT carries
      // the hax user id, never Google's. Verified against the pinned
      // next-auth version; a mismatch fails closed (FastAPI rejects a
      // non-UUID sub), it cannot leak.
      user.id = hax.id;
      user.email = hax.email;
      return true;
    },
    jwt({ token, user }) {
      if (user) {
        // First mint after a successful login (credentials or Google; signIn
        // above has already swapped in the hax id).
        token.sub = (user as { id: string }).id;
        token.email = user.email;
        token.auth_time = Math.floor(Date.now() / 1000);
        token.jti = crypto.randomUUID();
      }
      // Re-issues: return as-is — auth_time/jti must survive unchanged.
      return token;
    },
    session({ session, token }) {
      if (session.user) {
        session.user.id = token.sub as string;
        session.user.email = token.email as string;
      }
      return session;
    },
  },
  jwt: {
    maxAge: MAX_AGE_S,
    // Both halves overridden together or sessions break (spec: Auth.js config).
    async encode({ token }) {
      const { sub, email, auth_time, jti } = (token ?? {}) as Record<
        string,
        unknown
      >;
      return await new SignJWT({
        email,
        auth_time,
        jti: jti as string | undefined,
      })
        .setProtectedHeader({ alg: "HS256" })
        .setSubject(String(sub))
        .setIssuer(ISSUER)
        .setAudience(AUDIENCE)
        .setIssuedAt()
        .setExpirationTime(Math.floor(Date.now() / 1000) + MAX_AGE_S)
        .sign(key());
    },
    async decode({ token }) {
      if (!token) return null;
      try {
        const { payload } = await jwtVerify(token, key(), {
          issuer: ISSUER,
          audience: AUDIENCE,
          algorithms: ["HS256"],
        });
        return payload;
      } catch {
        // Invalid/expired cookie = signed out, not an error page.
        return null;
      }
    },
  },
});
