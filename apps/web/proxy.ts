import { NextResponse } from "next/server";

import { auth } from "@/auth";

// Session-gate every page except the auth surfaces. /verify-email,
// /forgot-password and /reset-password are reached from emailed links, so they
// must stay open to logged-out visitors; /auth/* is Auth.js's own machinery
// (signin/callback); /privacy is linked from the Google consent screen.
const PUBLIC_PREFIXES = [
  "/login",
  "/signup",
  "/verify-email",
  "/forgot-password",
  "/reset-password",
  "/auth",
  "/privacy",
];

// Gates Next pages only, and crypto-only (req.auth comes from auth.ts's
// decode): a revoked-but-unexpired session still gets page shells. The API's
// current_user is the real boundary — every data fetch behind them 401s.
// The logged-out target (/login) must stay in PUBLIC_PREFIXES or requests
// loop; the logged-in target (/chat) needn't — that request carries req.auth
// and clears the gate below.
export default auth((req) => {
  const { pathname } = req.nextUrl;
  const session = req.auth;
  // An anonymous demo visitor is a session with no email: they may reach the
  // auth screens (sign-up converts their row; login ends the demo).
  const member = Boolean(session?.user?.email);
  // The landing page is public by exact match ("/" as a prefix would open
  // everything). Members belong in the app. A returning visitor gets the
  // landing page again: their next send there starts a new demo (a new
  // anonymous user), so coming back to the front page starts fresh.
  if (pathname === "/") {
    return member
      ? NextResponse.redirect(new URL("/chat", req.nextUrl.origin))
      : NextResponse.next();
  }
  // A demo lives only on the landing page, which becomes the visitor's chat
  // in place (no URL for the conversation): reload or leave, and it is gone.
  // The app itself is for members.
  if (session && !member && pathname.startsWith("/chat")) {
    return NextResponse.redirect(new URL("/", req.nextUrl.origin));
  }
  // Members' visits to the auth screens bounce into the app — checked before
  // the public-prefix pass, which would otherwise let them through.
  if (
    member &&
    (pathname.startsWith("/login") || pathname.startsWith("/signup"))
  ) {
    return NextResponse.redirect(new URL("/chat", req.nextUrl.origin));
  }
  if (session || PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }
  return NextResponse.redirect(new URL("/login", req.nextUrl.origin));
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
