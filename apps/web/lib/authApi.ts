import type { components } from "@/lib/openapi";

// Thin typed fetch wrappers for the public auth routes (signup, resend,
// verify-email + its precheck, request/reset password + its precheck) — all
// called before a session cookie exists, so unlike chatApi.ts these carry no
// credentials.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

type AcceptedOut = components["schemas"]["AcceptedOut"];
type EmailOut = components["schemas"]["EmailOut"];
type TokenStatusOut = components["schemas"]["TokenStatusOut"];

// Server error codes the auth pages branch on. "validation" is a 422 —
// signup's bad email, or a too-short/too-long password on signup or
// reset-password — and carries `detail` so a caller can attribute it to a
// field; "unknown" covers everything else, including a network failure or an
// unparseable body (see the catch in `post` below).
export type Code = "invalid_token" | "rate_limited" | "validation" | "unknown";

// Narrows a server-supplied string before it can steer a page into a branch
// meant for a different code — an unrecognized value falls back to "unknown".
function isKnownCode(value: string | undefined): value is Code {
  return (
    value === "invalid_token" ||
    value === "rate_limited" ||
    value === "validation" ||
    value === "unknown"
  );
}

type Result<T> =
  | { ok: true; data: T }
  | { ok: false; code: Code; detail?: unknown };

async function post<T>(path: string, body: unknown): Promise<Result<T>> {
  // Everything below — the fetch itself and every body parse — is covered by
  // this one catch, so a network failure or a non-JSON response can never
  // throw out to a caller; every page already renders copy for "unknown".
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) return { ok: true, data: (await res.json()) as T };
    if (res.status === 429) return { ok: false, code: "rate_limited" };
    if (res.status === 422) {
      const errBody = (await res.json()) as { detail?: unknown };
      return { ok: false, code: "validation", detail: errBody.detail };
    }
    const errBody = (await res.json()) as { detail?: { code?: string } };
    const code = errBody.detail?.code;
    return { ok: false, code: isKnownCode(code) ? code : "unknown" };
  } catch {
    return { ok: false, code: "unknown" };
  }
}

export const signup = (email: string, password: string) =>
  post<AcceptedOut>("/api/auth/signup", { email, password });
export const resendVerification = (email: string) =>
  post<AcceptedOut>("/api/auth/resend-verification", { email });
export const verifyEmail = (token: string) =>
  post<EmailOut>("/api/auth/verify-email", { token });
export const checkVerifyToken = (token: string) =>
  post<TokenStatusOut>("/api/auth/verify-email/check", { token });
export const requestPasswordReset = (email: string) =>
  post<AcceptedOut>("/api/auth/request-password-reset", { email });
export const resetPassword = (token: string, password: string) =>
  post<EmailOut>("/api/auth/reset-password", { token, password });
export const checkResetToken = (token: string) =>
  post<TokenStatusOut>("/api/auth/reset-password/check", { token });
