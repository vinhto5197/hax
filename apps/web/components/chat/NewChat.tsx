"use client";

import { useState, useSyncExternalStore } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { pickGreeting } from "@/lib/greeting";

interface NewChatProps {
  // null for a visitor or a nameless member.
  name: string | null;
  // Example prompts; only the visitor's demo has any, so a non-empty list is
  // also what marks the screen as the visitor's.
  chips: string[];
  onSend: (text: string) => Promise<void>;
  error?: string | null;
  disabled?: boolean;
}

// The screen before a conversation exists: a greeting and the composer, no
// chat window. The caller swaps it for the ChatWindow on the first send, so
// nothing here survives into the conversation (the chips never return).
export function NewChat({
  name,
  chips,
  onSend,
  error,
  disabled = false,
}: NewChatProps) {
  // Picked once per mount so a re-render never swaps the line. The pick uses
  // the viewer's clock and a random choice, so the server's render cannot
  // match the browser's: the line is shown only once hydrated (the server
  // snapshot is "not mounted"), which keeps the server HTML and the client's
  // first render identical.
  const [greeting] = useState(() => pickGreeting(name));
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const visitor = chips.length > 0;

  return (
    <div className="mx-auto flex h-full w-full max-w-4xl flex-col justify-center gap-4 p-4">
      <h1 className="min-h-8 text-2xl font-semibold">
        {mounted ? greeting : "\u00a0"}
      </h1>
      {visitor ? (
        <p className="text-sm text-black/60 dark:text-white/60">
          Chat with your own documents. Try it without an account: ask about hax
          itself.
        </p>
      ) : null}
      {visitor ? (
        <div className="flex flex-wrap gap-2">
          {chips.map((chip) => (
            <button
              key={chip}
              type="button"
              disabled={disabled}
              onClick={() => void onSend(chip)}
              className="rounded-full border px-3 py-1 text-sm hover:bg-black/5 disabled:opacity-50 dark:hover:bg-white/10"
            >
              {chip}
            </button>
          ))}
        </div>
      ) : null}
      <ChatInput onSend={onSend} disabled={disabled} />
      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}
    </div>
  );
}
