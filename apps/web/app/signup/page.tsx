"use client";

import Link from "next/link";
import { useState, type SubmitEvent } from "react";

import { AuthCard, buttonClass, fieldClass } from "@/components/auth/AuthCard";
import { GoogleButton, OrDivider } from "@/components/auth/GoogleButton";
import { resendVerification, signup } from "@/lib/authApi";

// A FastAPI 422 detail is an array of { loc: [...] } items; loc names the
// failing field (["body","email"] | ["body","password"]). Narrow from unknown.
function pydanticEmailFailed(detail: unknown): boolean {
  if (!Array.isArray(detail)) return false;
  return detail.some(
    (item) =>
      typeof item === "object" &&
      item !== null &&
      "loc" in item &&
      Array.isArray((item as { loc: unknown }).loc) &&
      (item as { loc: unknown[] }).loc.includes("email"),
  );
}

// Resend is uniform on success (account existence never leaks) but not on
// rate limiting, which is safe to surface distinctly.
type ResendState = "idle" | "sending" | "sent" | "rate_limited" | "error";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Set on a successful signup; its presence swaps the form for the
  // check-your-inbox panel. The gate is on, so there's no auto sign-in here.
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [resendState, setResendState] = useState<ResendState>("idle");

  async function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await signup(email, password);
      if (!result.ok) {
        if (result.code === "rate_limited") {
          setError("Too many attempts — try again later.");
        } else if (result.code === "validation") {
          setError(
            pydanticEmailFailed(result.detail)
              ? "Please enter a valid email address."
              : "Password must be 8–128 characters.",
          );
        } else {
          setError("Signup failed.");
        }
        return;
      }
      setSentTo(email);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    // Only reachable once sentTo is set (the check-your-inbox panel below);
    // the guard satisfies the type.
    if (!sentTo) return;
    setResendState("sending");
    const result = await resendVerification(sentTo);
    setResendState(
      result.ok
        ? "sent"
        : result.code === "rate_limited"
          ? "rate_limited"
          : "error",
    );
  }

  if (sentTo) {
    return (
      <AuthCard title="Check your inbox">
        <p className="text-sm">
          We sent a verification link to {sentTo}. It expires in 24 hours.
        </p>
        <button
          type="button"
          onClick={handleResend}
          disabled={resendState === "sending"}
          className={buttonClass}
        >
          Didn&apos;t get it? Resend
        </button>
        {resendState === "sent" && (
          <p className="text-sm text-black/60 dark:text-white/60">Sent.</p>
        )}
        {resendState === "rate_limited" && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Too many attempts — try again in a few minutes.
          </p>
        )}
        {resendState === "error" && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Something went wrong. Please try again.
          </p>
        )}
        <p className="text-sm text-black/60 dark:text-white/60">
          <Link href="/login" className="underline">
            Back to log in
          </Link>
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Sign up for hax">
      <form onSubmit={handleSubmit} className="space-y-3">
        <input
          type="email"
          required
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={fieldClass}
        />
        <input
          type="password"
          required
          minLength={8}
          maxLength={128}
          placeholder="Password (8+ characters)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={fieldClass}
        />
        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        )}
        <button type="submit" disabled={submitting} className={buttonClass}>
          {submitting ? "Signing up…" : "Sign up"}
        </button>
      </form>
      <OrDivider />
      <GoogleButton label="Continue with Google" />
      <p className="text-sm text-black/60 dark:text-white/60">
        Already have an account?{" "}
        <Link href="/login" className="underline">
          Log in
        </Link>
      </p>
    </AuthCard>
  );
}
