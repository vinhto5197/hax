"use client";

import Link from "next/link";
import { useState } from "react";
import { signIn } from "next-auth/react";

import { ChatWindow } from "@/components/chat/ChatWindow";
import { ConversationsProvider } from "@/components/chat/ConversationsProvider";
import { NewChat } from "@/components/chat/NewChat";

// Example prompts for the visitor; each is answerable from the guest prompt
// alone (a visitor has no tools).
const DEMO_CHIPS = [
  "What database does hax use?",
  "Can another user see my files?",
  "How are my documents searched?",
];

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
          <ChatWindow
            conversationId={null}
            initialPrompt={initialPrompt}
            demo
          />
        </main>
      </ConversationsProvider>
    );
  }

  return (
    <main className="flex min-h-screen flex-col justify-center">
      <NewChat
        name={null}
        chips={DEMO_CHIPS}
        onSend={start}
        error={error}
        disabled={starting}
      />
      <p className="mx-auto w-full max-w-4xl px-4 pb-4 text-sm text-black/60 dark:text-white/60">
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
