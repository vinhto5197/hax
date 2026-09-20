"use client";

import { useState } from "react";

import { resendVerification } from "@/lib/authApi";

// Resend is uniform on success (account existence never leaks) but not on
// rate limiting, which is safe to surface distinctly.
export type ResendState =
  | "idle"
  | "sending"
  | "sent"
  | "rate_limited"
  | "error";

export function useResend() {
  const [state, setState] = useState<ResendState>("idle");

  async function resend(email: string) {
    setState("sending");
    const result = await resendVerification(email);
    setState(
      result.ok
        ? "sent"
        : result.code === "rate_limited"
          ? "rate_limited"
          : "error",
    );
  }

  return { state, resend, reset: () => setState("idle") };
}

export function ResendStatus({
  state,
  sentCopy = "Sent.",
}: {
  state: ResendState;
  sentCopy?: string;
}) {
  if (state === "sent") {
    return (
      <p className="text-sm text-black/60 dark:text-white/60">{sentCopy}</p>
    );
  }
  if (state === "rate_limited") {
    return (
      <p className="text-sm text-red-600 dark:text-red-400">
        Too many attempts — try again in a few minutes.
      </p>
    );
  }
  if (state === "error") {
    return (
      <p className="text-sm text-red-600 dark:text-red-400">
        Something went wrong. Please try again.
      </p>
    );
  }
  return null;
}
