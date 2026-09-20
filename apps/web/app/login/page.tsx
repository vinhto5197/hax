"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type SubmitEvent } from "react";
import { signIn } from "next-auth/react";

import { AuthCard, buttonClass, fieldClass } from "@/components/auth/AuthCard";
import { GoogleButton, OrDivider } from "@/components/auth/GoogleButton";
import { ResendStatus, useResend } from "@/components/auth/useResend";

// Google failures come back as a redirect to /login?error=... — the two codes
// below are ours (auth.ts signIn callback); anything else is Auth.js's own
// (OAuthCallbackError, OAuthAccountNotLinked, ...) and gets the generic line.
function oauthErrorMessage(code: string | null): string | null {
  if (!code) return null;
  if (code === "google_unverified")
    return "Google hasn't verified that email address, so it can't be used to sign in.";
  return "Google sign-in didn't complete. Please try again.";
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Arrival from /verify-email (?verified=1) or from /reset-password's
  // fallback (?reset=1), each with &email=…: a one-hop, same-origin hand-off
  // via router.replace (client navigation, never sent to the API, no history
  // entry for the spent link). Read once, on mount.
  const arrivalBanner =
    searchParams.get("reset") === "1"
      ? "Password updated — log in to continue."
      : searchParams.get("verified") === "1"
        ? "Email verified — log in to continue."
        : null;
  const [email, setEmail] = useState(() => searchParams.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(() =>
    oauthErrorMessage(searchParams.get("error")),
  );
  const [submitting, setSubmitting] = useState(false);
  // Non-null only after a 403 (email_unverified); arms the Resend button.
  const [unverifiedEmail, setUnverifiedEmail] = useState<string | null>(null);
  // Shown only for the generic "Invalid email or password." outcome, never
  // alongside the rate-limit or unverified-email messages.
  const [showGoogleHint, setShowGoogleHint] = useState(false);
  const { state: resendState, resend, reset: resetResend } = useResend();

  async function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setUnverifiedEmail(null);
    setShowGoogleHint(false);
    resetResend();
    try {
      // redirect:false so failures stay on this page with one generic
      // message (wrong password vs no account is deliberately
      // indistinguishable).
      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });
      if (result?.error) {
        // authorize() throws RateLimit ("rate_limited") on 429 and
        // EmailUnverified ("email_unverified") on 403; both are safe to
        // distinguish (no account-existence leak). Everything else collapses
        // to the generic anti-enumeration message.
        if (result.code === "rate_limited") {
          setError("Too many attempts — try again in a few minutes.");
        } else if (result.code === "email_unverified") {
          setError("Verify your email first — check your inbox for the link.");
          setUnverifiedEmail(email);
        } else {
          setError("Invalid email or password.");
          setShowGoogleHint(true);
        }
        return;
      }
      router.push("/chat");
      router.refresh();
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    if (!unverifiedEmail) return;
    await resend(unverifiedEmail);
  }

  return (
    <AuthCard title="Log in to hax">
      {arrivalBanner && (
        <p className="text-sm text-green-600 dark:text-green-400">
          {arrivalBanner}
        </p>
      )}
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
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={fieldClass}
        />
        {error && (
          <div className="space-y-1">
            <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
            {showGoogleHint && (
              <p className="text-sm text-black/60 dark:text-white/60">
                Signed up with Google? Use the button below — or reset your
                password to add one.
              </p>
            )}
            {unverifiedEmail && (
              <button
                type="button"
                onClick={handleResend}
                disabled={resendState === "sending"}
                className="text-sm underline disabled:opacity-50"
              >
                Resend verification email
              </button>
            )}
            <ResendStatus state={resendState} />
          </div>
        )}
        <button type="submit" disabled={submitting} className={buttonClass}>
          {submitting ? "Logging in…" : "Log in"}
        </button>
      </form>
      <OrDivider />
      <GoogleButton label="Continue with Google" />
      <p className="text-sm text-black/60 dark:text-white/60">
        No account?{" "}
        <Link href="/signup" className="underline">
          Sign up
        </Link>{" "}
        ·{" "}
        <Link href="/forgot-password" className="underline">
          Forgot password?
        </Link>
      </p>
    </AuthCard>
  );
}

export default function LoginPage() {
  // useSearchParams requires a Suspense boundary for the build's static pass;
  // the fallback mirrors the real card so the prerendered page isn't blank.
  return (
    <Suspense fallback={<AuthCard title="Log in to hax">{null}</AuthCard>}>
      <LoginForm />
    </Suspense>
  );
}
