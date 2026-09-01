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

// Gates Next pages only, and crypto-only (req.auth comes from auth.ts's
// decode): a revoked-but-unexpired session still gets page shells. The API's
// current_user is the real boundary — every data fetch behind them 401s.
// Redirect targets must stay in PUBLIC_PREFIXES or requests loop.
export default auth((req) => {
  const { pathname } = req.nextUrl;
  // Logged-in visits to the auth screens bounce into the app — checked before
  // the public-prefix pass, which would otherwise let them through.
  if (
    req.auth &&
    (pathname.startsWith("/login") || pathname.startsWith("/signup"))
  ) {
    return NextResponse.redirect(new URL("/", req.nextUrl.origin));
  }
  if (req.auth || PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }
  return NextResponse.redirect(new URL("/login", req.nextUrl.origin));
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
