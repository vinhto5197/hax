"use client";

import Link from "next/link";
import { useState } from "react";
import { signIn } from "next-auth/react";

import { ChatWindow } from "@/components/chat/ChatWindow";
import { ConversationsProvider } from "@/components/chat/ConversationsProvider";
import { NewChat } from "@/components/chat/NewChat";
import { EvolvingNotice } from "@/components/EvolvingNotice";
import { Wordmark } from "@/components/Wordmark";

// Example prompts for the visitor; each is answerable from the guest prompt
// alone (a visitor has no tools).
const DEMO_CHIPS = [
  "What database does Hax use?",
  "Can another user see my files?",
  "How are my documents searched?",
];

const FOOTER_LINKS = [{ href: "/privacy", label: "Privacy" }] as const;

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
        <main className="h-dvh">
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
    <main className="flex min-h-dvh flex-col justify-center">
      <header className="flex w-full items-center justify-between px-8 py-4 text-ink">
        <Wordmark />
        <nav className="flex items-center gap-4">
          <Link href="/login" className="text-small text-ink-2 hover:underline">
            Log in
          </Link>
          <Link
            href="/signup"
            className="rounded-control bg-accent px-3 py-1.5 text-small font-medium text-accent-ink"
          >
            Sign up
          </Link>
        </nav>
      </header>
      <EvolvingNotice />
      <div className="grid flex-1">
        <NewChat
          name={null}
          chips={DEMO_CHIPS}
          onSend={start}
          error={error}
          disabled={starting}
        />
      </div>
      <nav className="flex justify-center gap-2 px-4 pb-4 text-small text-ink-2">
        {FOOTER_LINKS.map((link, i) => (
          <span key={link.href} className="flex gap-2">
            {i > 0 ? <span aria-hidden="true">·</span> : null}
            <Link href={link.href} className="hover:underline">
              {link.label}
            </Link>
          </span>
        ))}
      </nav>
    </main>
  );
}
