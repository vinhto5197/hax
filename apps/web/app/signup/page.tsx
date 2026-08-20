"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type SubmitEvent } from "react";
import { signIn } from "next-auth/react";

import { AuthCard, buttonClass, fieldClass } from "@/components/auth/AuthCard";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const response = await fetch(`${API_BASE}/api/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) {
      let detail = "Signup failed.";
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === "string") detail = body.detail;
        else if (response.status === 422)
          detail = "Password must be 8–128 characters.";
      } catch {
        // keep the generic message
      }
      setError(detail);
      setSubmitting(false);
      return;
    }
    // Slice 1: account is immediately usable (verification gate lands in
    // slice 4) — log straight in.
    const result = await signIn("credentials", {
      email,
      password,
      redirect: false,
    });
    if (result?.error) {
      router.push("/login");
      return;
    }
    router.push("/chat");
    router.refresh();
  }

  return (
    <AuthCard title="Sign up for hax">
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
          minLength={8}
          maxLength={128}
          placeholder="Password (8+ characters)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={fieldClass}
        />
        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        )}
        <button type="submit" disabled={submitting} className={buttonClass}>
          {submitting ? "Signing up…" : "Sign up"}
        </button>
      </form>
      <p className="text-sm text-black/60 dark:text-white/60">
        Already have an account?{" "}
        <Link href="/login" className="underline">
          Log in
        </Link>
      </p>
    </AuthCard>
  );
}
