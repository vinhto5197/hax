// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The Auth.js handlers are replaced so each test sees whether the request
// reached them; the route under test is the module the app serves.
const authHandlers = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
}));

vi.mock("@/auth", () => ({ handlers: authHandlers }));

import { GET, POST } from "@/app/auth/[...nextauth]/route";

const ORIGIN = "http://localhost:3000";

function request(path: string, init?: { method?: string; body?: string }) {
  return new NextRequest(new URL(path, ORIGIN), init);
}

beforeEach(() => {
  authHandlers.GET.mockResolvedValue(new Response("from-authjs-get"));
  authHandlers.POST.mockResolvedValue(new Response("from-authjs-post"));
});

describe("GET /auth/[...nextauth]", () => {
  it("sends a Google callback carrying error=access_denied to /login?error=OAuthCallbackError without calling Auth.js", async () => {
    const res = await GET(
      request("/auth/callback/google?error=access_denied&state=x"),
    );

    expect([302, 307]).toContain(res.status);
    const location = res.headers.get("location");
    expect(location).not.toBeNull();
    const target = new URL(location!, ORIGIN);
    expect(target.origin).toBe(ORIGIN);
    expect(target.pathname).toBe("/login");
    expect(target.searchParams.get("error")).toBe("OAuthCallbackError");
    expect(authHandlers.GET).not.toHaveBeenCalled();
  });

  it("never names the container's bind origin (0.0.0.0) in the redirect for an access_denied callback; the Location is relative or 0.0.0.0-free and resolves to /login?error=OAuthCallbackError", async () => {
    const res = await GET(
      new NextRequest(
        "https://0.0.0.0:3000/auth/callback/google?error=access_denied&state=x",
      ),
    );

    expect([302, 307]).toContain(res.status);
    const location = res.headers.get("location");
    expect(location).not.toBeNull();
    expect(location).not.toContain("0.0.0.0");
    const target = new URL(location!, ORIGIN);
    expect(target.pathname).toBe("/login");
    expect(target.searchParams.get("error")).toBe("OAuthCallbackError");
    expect(authHandlers.GET).not.toHaveBeenCalled();
  });

  it("passes a normal Google callback (code + state) to the Auth.js GET handler unchanged and returns its response", async () => {
    const req = request("/auth/callback/google?code=abc&state=x");
    const res = await GET(req);

    expect(authHandlers.GET).toHaveBeenCalledTimes(1);
    expect(authHandlers.GET.mock.calls[0][0]).toBe(req);
    expect(await res.text()).toBe("from-authjs-get");
  });

  it("passes a Google callback with a provider error other than access_denied to Auth.js unchanged", async () => {
    const req = request("/auth/callback/google?error=server_error&state=x");
    const res = await GET(req);

    expect(authHandlers.GET).toHaveBeenCalledTimes(1);
    expect(authHandlers.GET.mock.calls[0][0]).toBe(req);
    expect(await res.text()).toBe("from-authjs-get");
  });

  it("passes a non-callback request (/auth/session) to Auth.js", async () => {
    const req = request("/auth/session");
    const res = await GET(req);

    expect(authHandlers.GET).toHaveBeenCalledTimes(1);
    expect(authHandlers.GET.mock.calls[0][0]).toBe(req);
    expect(await res.text()).toBe("from-authjs-get");
  });
});

describe("POST /auth/[...nextauth]", () => {
  it("is still the Auth.js POST handler", async () => {
    const req = request("/auth/callback/credentials", {
      method: "POST",
      body: "email=a%40b.c",
    });
    const res = await POST(req);

    expect(authHandlers.POST).toHaveBeenCalledTimes(1);
    expect(authHandlers.POST.mock.calls[0][0]).toBe(req);
    expect(authHandlers.GET).not.toHaveBeenCalled();
    expect(await res.text()).toBe("from-authjs-post");
  });
});
