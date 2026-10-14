import { beforeEach, describe, expect, it, vi } from "vitest";

import * as authApi from "@/lib/authApi";
import type { paths } from "@/lib/openapi";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

const calls: Array<[string, keyof paths, object, () => Promise<unknown>]> = [
  [
    "signup",
    "/api/auth/signup",
    { email: "a@b.co", password: "pw-123456", name: "Ann" },
    () => authApi.signup("a@b.co", "pw-123456", "Ann"),
  ],
  [
    "resendVerification",
    "/api/auth/resend-verification",
    { email: "a@b.co" },
    () => authApi.resendVerification("a@b.co"),
  ],
  [
    "verifyEmail",
    "/api/auth/verify-email",
    { token: "t1" },
    () => authApi.verifyEmail("t1"),
  ],
  [
    "requestPasswordReset",
    "/api/auth/request-password-reset",
    { email: "a@b.co" },
    () => authApi.requestPasswordReset("a@b.co"),
  ],
  [
    "resetPassword",
    "/api/auth/reset-password",
    { token: "t1", password: "pw-123456" },
    () => authApi.resetPassword("t1", "pw-123456"),
  ],
  [
    "checkResetToken",
    "/api/auth/reset-password/check",
    { token: "t1" },
    () => authApi.checkResetToken("t1"),
  ],
];

describe.each(calls)("%s", (_name, path, body, invoke) => {
  it(`POSTs JSON to ${path} without a credentials option`, async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    await invoke();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init = {}] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(path);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("content-type")).toBe(
      "application/json",
    );
    expect(JSON.parse(init.body as string)).toEqual(body);
    expect("credentials" in init).toBe(false);
  });

  it("resolves a 2xx to ok with the parsed body", async () => {
    const data = { detail: "done", extra: 1 };
    fetchMock.mockResolvedValue(jsonResponse(data, 200));
    await expect(invoke()).resolves.toEqual({ ok: true, data });
  });
});

describe("failures", () => {
  it.each([
    [
      "a 429 with JSON",
      "rate_limited",
      () => jsonResponse({ detail: "slow down" }, 429),
    ],
    [
      "a 429 with a non-JSON body",
      "rate_limited",
      () => new Response("Too Many Requests", { status: 429 }),
    ],
    [
      "a 400 with code invalid_token",
      "invalid_token",
      () => jsonResponse({ detail: { code: "invalid_token" } }, 400),
    ],
    [
      "a 403 with an unlisted code",
      "unknown",
      () => jsonResponse({ detail: { code: "demo_limit" } }, 403),
    ],
    [
      "a 400 with a string detail",
      "unknown",
      () => jsonResponse({ detail: "Bad request" }, 400),
    ],
    [
      "a network failure",
      "unknown",
      () => Promise.reject(new TypeError("Failed to fetch")),
    ],
    [
      "a non-JSON 500",
      "unknown",
      () => new Response("Internal Server Error", { status: 500 }),
    ],
    [
      "a non-JSON 200",
      "unknown",
      () => new Response("<html>ok</html>", { status: 200 }),
    ],
  ])("%s → %s", async (_label, code, respond) => {
    fetchMock.mockImplementation(async () => respond());
    await expect(authApi.verifyEmail("t1")).resolves.toStrictEqual({
      ok: false,
      code,
    });
  });

  it("a 422 → validation carrying the field errors", async () => {
    const detail = [
      { loc: ["body", "token"], msg: "Field required", type: "missing" },
    ];
    fetchMock.mockResolvedValue(jsonResponse({ detail }, 422));
    await expect(authApi.verifyEmail("t1")).resolves.toStrictEqual({
      ok: false,
      code: "validation",
      detail,
    });
  });
});
