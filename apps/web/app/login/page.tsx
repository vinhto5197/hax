"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type SubmitEvent } from "react";
import { signIn } from "next-auth/react";

import { AuthCard, buttonClass, fieldClass } from "@/components/auth/AuthCard";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
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
      {/* "Continue with Google" lands here in slice 3, below the form. */}
      <p className="text-sm text-black/60 dark:text-white/60">
        No account?{" "}
        <Link href="/signup" className="underline">
          Sign up
        </Link>
      </p>
    </AuthCard>
  );
}
