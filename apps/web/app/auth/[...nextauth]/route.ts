import type { NextRequest } from "next/server";

import { handlers } from "@/auth";

// A new Google account that cancels the consent screen comes back with
// error=access_denied and no `iss`; the OAuth library checks `iss` first and
// throws a generic error, which Auth.js reports as Configuration ("temporarily
// unavailable"). Answer that one case as the retryable OAuth error it is,
// before Auth.js sees it; every other request is Auth.js's. The Location is
// relative: behind the proxy, request.nextUrl carries the container's bind
// address (Auth.js swaps in AUTH_URL only inside its own handlers).
export async function GET(request: NextRequest): Promise<Response> {
  const url = request.nextUrl;
  if (
    url.pathname.endsWith("/callback/google") &&
    url.searchParams.get("error") === "access_denied"
  ) {
    return new Response(null, {
      status: 302,
      headers: { Location: "/login?error=OAuthCallbackError" },
    });
  }
  return handlers.GET(request);
}

export const { POST } = handlers;
