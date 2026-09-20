"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type SubmitEvent } from "react";
import { signIn } from "next-auth/react";

import { AuthCard, buttonClass, fieldClass } from "@/components/auth/AuthCard";
import { resetPassword } from "@/lib/authApi";

type ErrorCode = "invalid_token" | "rate_limited" | "validation" | "unknown";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // No token behaves exactly like an invalid/expired one — set once, up
  // front, with nothing to retry.
  const [errorCode, setErrorCode] = useState<ErrorCode | null>(
    token ? null : "invalid_token",
  );
  const [mismatch, setMismatch] = useState(false);

  async function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    if (!token) {
      setErrorCode("invalid_token");
      return;
    }
    setSubmitting(true);
    setErrorCode(null);
    try {
      const result = await resetPassword(token, password);
      if (!result.ok) {
        setErrorCode(result.code);
        return;
      }
      // The reset already succeeded server-side, so a credentials failure
      // here (e.g. the login rate limiter, tripped by earlier failed
      // attempts) must not read as the reset itself failing. Land on the
      // password-updated banner and let the user log in by hand rather than
      // pushing to /chat on a sign-in that didn't happen.
      const signInResult = await signIn("credentials", {
        email: result.data.email,
        password,
        redirect: false,
      });
      if (signInResult?.error) {
        router.replace(
          `/login?reset=1&email=${encodeURIComponent(result.data.email)}`,
        );
        return;
      }
      router.push("/chat");
      router.refresh();
    } finally {
      setSubmitting(false);
    }
  }

  if (errorCode === "invalid_token") {
    return (
      <AuthCard title="Reset your password">
        <p className="text-sm text-red-600 dark:text-red-400">
          This link is invalid or has expired.
        </p>
        <p className="text-sm text-black/60 dark:text-white/60">
          <Link href="/forgot-password" className="underline">
            Request a new link
          </Link>
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Choose a new password">
      <form onSubmit={handleSubmit} className="space-y-3">
        <input
          type="password"
          required
          minLength={8}
          maxLength={128}
          placeholder="New password (8+ characters)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={fieldClass}
        />
        <input
          type="password"
          required
          minLength={8}
          maxLength={128}
          placeholder="Confirm new password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          className={fieldClass}
        />
        {mismatch && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Passwords don&apos;t match.
          </p>
        )}
        {errorCode && (
          <p className="text-sm text-red-600 dark:text-red-400">
            {errorCode === "rate_limited"
              ? "Too many attempts — try again in a few minutes."
              : errorCode === "validation"
                ? "Password must be 8–128 characters."
                : "Something went wrong. Please try again."}
          </p>
        )}
        <button type="submit" disabled={submitting} className={buttonClass}>
          {submitting ? "Saving…" : "Save new password"}
        </button>
      </form>
    </AuthCard>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={<AuthCard title="Choose a new password">{null}</AuthCard>}
    >
      <ResetPasswordForm />
    </Suspense>
  );
}
