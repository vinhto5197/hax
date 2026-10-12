"use client";

import Link from "next/link";
import { useState, type SubmitEvent } from "react";

import { AuthCard, buttonClass, fieldClass } from "@/components/auth/AuthCard";
import { requestPasswordReset } from "@/lib/authApi";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Set once the request completes; presence swaps to the uniform "if an
  // account exists" panel — anti-enumeration, so it shows on every outcome.
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await requestPasswordReset(email);
    setSubmitting(false);
    if (!result.ok) {
      setError(
        result.code === "rate_limited"
          ? "Too many attempts — try again in a few minutes."
          : result.code === "validation"
            ? "Please enter a valid email address."
            : "Something went wrong. Please try again.",
      );
      return;
    }
    setSentTo(email);
  }

  if (sentTo) {
    return (
      <AuthCard title="Check your inbox">
        <p className="text-body">
          If an account exists for {sentTo}, we&apos;ve sent a reset link (valid
          for 1 hour).
        </p>
        <p className="text-small text-ink-2">
          <Link
            href="/login"
            className="text-accent underline underline-offset-2"
          >
            Back to log in
          </Link>
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Forgot password">
      <form onSubmit={handleSubmit} className="space-y-3">
        <input
          type="email"
          required
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={fieldClass}
        />
        {error && <p className="text-small text-status-failed">{error}</p>}
        <button type="submit" disabled={submitting} className={buttonClass}>
          {submitting ? "Sending…" : "Send reset link"}
        </button>
      </form>
      <p className="text-small text-ink-2">
        <Link
          href="/login"
          className="text-accent underline underline-offset-2"
        >
          Back to log in
        </Link>
      </p>
    </AuthCard>
  );
}
