import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { SignJWT, jwtVerify } from "jose";

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
        // Any failure -> null -> one generic UI message (anti-enumeration).
        if (!res.ok) return null;
        return (await res.json()) as {
          id: string;
          email: string;
          name: string | null;
        };
      },
    }),
  ],
  callbacks: {
    jwt({ token, user }) {
      if (user) {
        // First mint after a successful login.
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
