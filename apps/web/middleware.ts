import { NextResponse } from "next/server";

import { auth } from "@/auth";

// Session-gate every page except the auth surfaces. /verify-email,
// /forgot-password and /reset-password are reached from emailed links, so they
// must stay open to logged-out visitors; /auth/* is Auth.js's own machinery
// (signin/callback).
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
// The logged-out target (/login) must stay in PUBLIC_PREFIXES or requests
// loop; the logged-in target (/chat) needn't — that request carries req.auth
// and clears the gate below.
export default auth((req) => {
  const { pathname } = req.nextUrl;
  // Logged-in visits to the auth screens bounce into the app — checked before
  // the public-prefix pass, which would otherwise let them through. "/" is a
  // placeholder, so the app's entry is /chat.
  if (
    req.auth &&
    (pathname.startsWith("/login") || pathname.startsWith("/signup"))
  ) {
    return NextResponse.redirect(new URL("/chat", req.nextUrl.origin));
  }
  if (req.auth || PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }
  return NextResponse.redirect(new URL("/login", req.nextUrl.origin));
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
