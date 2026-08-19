import { NextResponse } from "next/server";

import { auth } from "@/auth";

// Session-gate every page except the auth surfaces. /verify-email,
// /forgot-password, /reset-password are pre-listed for slice 4 (404 until
// built — harmless). /auth/* is Auth.js's own machinery (signin/callback).
const PUBLIC_PREFIXES = [
  "/login",
  "/signup",
  "/verify-email",
  "/forgot-password",
  "/reset-password",
  "/auth",
];

// PRIMER (dev note — trim for prod). How this file executes:
// - Next calls the DEFAULT EXPORT once per matcher-matched request, BEFORE
//   routing to any page/route handler. `auth(cb)` is a higher-order call:
//   Auth.js returns a wrapped middleware that (1) reads the session cookie,
//   (2) verifies it with our custom decode (auth.ts — HS256, iss/aud), and
//   (3) attaches the verdict as `req.auth` (session object | null), THEN
//   invokes our callback. Auth.js does the crypto; the callback is policy.
// - Return values: NextResponse.next() = proceed to the destination;
//   NextResponse.redirect() = answer now, destination never runs.
// - Redirect targets must be PUBLIC_PREFIXES members or requests loop.
// - Scope: guards Next pages/routes ONLY. Browser->FastAPI calls never pass
//   through Next; the API's current_user (crypto + revocation) is the real
//   security boundary. This check is crypto-only: a revoked-but-unexpired
//   session still gets page shells — every data fetch behind them 401s.
export default auth((req) => {
  const { pathname } = req.nextUrl;
  if (req.auth || PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }
  return NextResponse.redirect(new URL("/login", req.nextUrl.origin));
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
