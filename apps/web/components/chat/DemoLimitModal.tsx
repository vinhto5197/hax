"use client";

import Link from "next/link";

import { buttonClass } from "@/components/auth/AuthCard";

// Shown when the API refuses an anonymous visitor's turn (403 demo_limit). The
// demo conversation is not carried over: an account starts fresh, with the
// visitor's own documents.
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
          Sign up to keep chatting, over your own documents.
        </p>
        <Link href="/signup" className={`block text-center ${buttonClass}`}>
          Sign up
        </Link>
        <p className="text-sm text-black/60 dark:text-white/60">
          <Link href="/login" className="underline">
            Log in
          </Link>{" "}
          if you already have an account.
        </p>
      </div>
    </div>
  );
}
