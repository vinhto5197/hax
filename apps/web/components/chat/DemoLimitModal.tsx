"use client";

import Link from "next/link";

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
      <div className="w-full max-w-sm space-y-4 rounded-card border border-border bg-surface-1 p-6">
        <h2 id="demo-limit-title" className="text-title font-semibold text-ink">
          End of the demo
        </h2>
        <p className="text-body text-ink">
          Sign up to keep chatting, over your own documents.
        </p>
        <Link
          href="/signup"
          className="block rounded-control bg-accent px-4 py-2 text-center text-body font-medium text-accent-ink"
        >
          Sign up
        </Link>
        <p className="text-small text-ink-2">
          <Link href="/login" className="text-accent hover:underline">
            Log in
          </Link>{" "}
          if you already have an account.
        </p>
      </div>
    </div>
  );
}
