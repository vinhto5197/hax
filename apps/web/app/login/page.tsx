"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type SubmitEvent } from "react";
import { signIn } from "next-auth/react";

import { AuthCard, buttonClass, fieldClass } from "@/components/auth/AuthCard";
import { GoogleButton, OrDivider } from "@/components/auth/GoogleButton";

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
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(() =>
    oauthErrorMessage(searchParams.get("error")),
  );
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    // redirect:false so failures stay on this page with one generic message
    // (wrong password vs no account is deliberately indistinguishable).
    const result = await signIn("credentials", {
      email,
      password,
      redirect: false,
    });
    if (result?.error) {
      // authorize() throws RateLimit (code "rate_limited") on 429; all other
      // failures collapse to the generic anti-enumeration message.
      setError(
        result.code === "rate_limited"
          ? "Too many attempts — try again in a few minutes."
          : "Invalid email or password.",
      );
      setSubmitting(false);
      return;
    }
    router.push("/chat");
    router.refresh();
  }

  return (
    <AuthCard title="Log in to hax">
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
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
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
