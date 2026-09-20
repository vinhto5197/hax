"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type SubmitEvent } from "react";

import { AuthCard, buttonClass, fieldClass } from "@/components/auth/AuthCard";
import { ResendStatus, useResend } from "@/components/auth/useResend";
import { verifyEmail } from "@/lib/authApi";

type Status = "idle" | "verifying" | "invalid_token";

function VerifyEmailForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  // No token behaves exactly like an invalid/expired one — set once, up
  // front, with nothing to retry.
  const [status, setStatus] = useState<Status>(
    token ? "idle" : "invalid_token",
  );
  // A rate-limited or unexpected failure on Confirm is transient, so it's
  // shown above the still-enabled Confirm button rather than switching views
  // — only an actually invalid/consumed token moves to the resend state.
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const { state: resendState, resend } = useResend();

  // Only ever called from the Confirm click, never on mount: corporate mail
  // scanners pre-fetch links in transit and would burn the single-use token
  // before the user gets here.
  async function handleConfirm() {
    if (!token) return;
    setStatus("verifying");
    setConfirmError(null);
    const result = await verifyEmail(token);
    if (!result.ok) {
      if (result.code === "invalid_token") {
        setStatus("invalid_token");
      } else {
        setStatus("idle");
        setConfirmError(
          result.code === "rate_limited"
            ? "Too many attempts — try again in a few minutes."
            : "Something went wrong. Please try again.",
        );
      }
      return;
    }
    router.replace(
      `/login?verified=1&email=${encodeURIComponent(result.data.email)}`,
    );
  }

  async function handleResendSubmit(event: SubmitEvent) {
    event.preventDefault();
    await resend(email);
  }

  if (status === "invalid_token") {
    return (
      <AuthCard title="Verify your email">
        <p className="text-sm text-red-600 dark:text-red-400">
          This link is invalid or has expired.
        </p>
        <form onSubmit={handleResendSubmit} className="space-y-2">
          <input
            type="email"
            required
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={fieldClass}
          />
          <button
            type="submit"
            disabled={resendState === "sending"}
            className={buttonClass}
          >
            Send a new link
          </button>
        </form>
        <ResendStatus
          state={resendState}
          sentCopy="Sent — if an account exists, a new link is on its way."
        />
        <p className="text-sm text-black/60 dark:text-white/60">
          <Link href="/login" className="underline">
            Back to log in
          </Link>
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Confirm your email">
      {confirmError && (
        <p className="text-sm text-red-600 dark:text-red-400">{confirmError}</p>
      )}
      <button
        type="button"
        disabled={status === "verifying"}
        onClick={handleConfirm}
        className={buttonClass}
      >
        {status === "verifying" ? "Verifying…" : "Confirm"}
      </button>
    </AuthCard>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<AuthCard title="Confirm your email">{null}</AuthCard>}>
      <VerifyEmailForm />
    </Suspense>
  );
}
