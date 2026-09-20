"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type SubmitEvent } from "react";

import { AuthCard, buttonClass, fieldClass } from "@/components/auth/AuthCard";
import {
  checkVerifyToken,
  resendVerification,
  verifyEmail,
} from "@/lib/authApi";

type Status = "checking" | "idle" | "verifying" | "invalid_token";
// Resend is uniform on success (account existence never leaks) but not on
// rate limiting, which is safe to surface distinctly.
type ResendState = "idle" | "sending" | "sent" | "rate_limited" | "error";

function VerifyEmailForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  // No token behaves exactly like an invalid/expired one — set once, up
  // front, with nothing to retry. A present token starts "checking" until
  // the precheck below resolves.
  const [status, setStatus] = useState<Status>(
    token ? "checking" : "invalid_token",
  );
  // A rate-limited or unexpected failure on Confirm is transient, so it's
  // shown above the still-enabled Confirm button rather than switching views
  // — only an actually invalid/consumed token moves to the resend state.
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [resendState, setResendState] = useState<ResendState>("idle");
  // Keyed by token, not just mount: StrictMode's double-invoke is deduped
  // (same token skipped) but a client-side navigation to a new link's token
  // still reruns the precheck.
  const lastCheckedToken = useRef<string | null>(null);

  useEffect(() => {
    if (!token || lastCheckedToken.current === token) return;
    lastCheckedToken.current = token;
    // Precheck only — the consuming call still waits for the click.
    checkVerifyToken(token).then((result) => {
      if (!result.ok && result.code === "invalid_token") {
        setStatus("invalid_token");
      } else {
        // ok, rate_limited, or unknown: a check failure must not block a
        // valid link, so fall through to the Confirm form and let the
        // consuming call decide.
        setStatus("idle");
      }
    });
  }, [token]);

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
    setResendState("sending");
    const result = await resendVerification(email);
    setResendState(
      result.ok
        ? "sent"
        : result.code === "rate_limited"
          ? "rate_limited"
          : "error",
    );
  }

  if (status === "checking") {
    return (
      <AuthCard title="Confirm your email">
        <p className="text-sm text-black/60 dark:text-white/60">
          Checking your link…
        </p>
      </AuthCard>
    );
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
        {resendState === "sent" && (
          <p className="text-sm text-black/60 dark:text-white/60">
            Sent — if an account exists, a new link is on its way.
          </p>
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
