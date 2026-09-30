"use client";

import Link from "next/link";
import { useState } from "react";
import { signIn } from "next-auth/react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { ConversationsProvider } from "@/components/chat/ConversationsProvider";

// Public landing (proxy.ts: exact-match "/"; members are sent to /chat). The
// first send starts a demo — a new anonymous session — and the chat renders
// here, in place, with no URL: reload or leave and it is gone. The provider
// mounts only after the session exists: its first list fetch would otherwise
// 401 and sign out.
export default function Home() {
  const [initialPrompt, setInitialPrompt] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(prompt: string) {
    setStarting(true);
    setError(null);
    const result = await signIn("anonymous", { redirect: false });
    if (!result || result.error) {
      setError(
        result?.code === "rate_limited"
          ? "Too many demo sessions from your network today. Log in, or try again tomorrow."
          : "Couldn't start the demo. Please try again.",
      );
      setStarting(false);
      return;
    }
    setInitialPrompt(prompt);
  }

  if (initialPrompt !== null) {
    return (
      <ConversationsProvider>
        <main className="h-screen">
          <ChatWindow conversationId={null} demo={{ initialPrompt }} />
        </main>
      </ConversationsProvider>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col justify-center gap-4 p-4">
      <h1 className="text-2xl font-bold">hax</h1>
      <p className="text-sm text-black/60 dark:text-white/60">
        Chat with your own documents. Try it without an account: ask about hax
        itself, e.g. what database it uses or whether another user can see your
        files.
      </p>
      <ChatInput onSend={start} disabled={starting} />
      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}
      <p className="text-sm text-black/60 dark:text-white/60">
        Have an account?{" "}
        <Link href="/login" className="underline">
          Log in
        </Link>{" "}
        ·{" "}
        <Link href="/privacy" className="underline">
          Privacy
        </Link>
      </p>
    </main>
  );
}
