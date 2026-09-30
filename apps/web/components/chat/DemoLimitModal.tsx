"use client";

import Link from "next/link";

import { buttonClass } from "@/components/auth/AuthCard";

// Shown when the API refuses an anonymous visitor's turn or upload (403
// demo_limit). Sign-up converts the visitor's own account, so the
// conversation is kept; signing in to an existing account leaves it behind.
export function DemoLimitModal() {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="demo-limit-title"
      className="fixed inset-0 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-sm space-y-4 rounded-lg border border-black/10 bg-background p-6 dark:border-white/10">
        <h2 id="demo-limit-title" className="text-xl font-bold">
          End of the demo
        </h2>
        <p className="text-sm">
          Sign up to keep this conversation and keep chatting.
        </p>
        <Link href="/signup" className={`block text-center ${buttonClass}`}>
          Sign up
        </Link>
        <p className="text-sm text-black/60 dark:text-white/60">
          <Link href="/login" className="underline">
            Log in
          </Link>{" "}
          instead (the demo conversation stays with the guest session).
        </p>
      </div>
    </div>
  );
}
