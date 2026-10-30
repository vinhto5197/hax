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
  // The model for the first turn; `onModelChange` marks a member and shows
  // the select (a visitor has no choice, and `name` is no marker: a nameless
  // member exists).
  model?: string;
  onModelChange?: (value: string) => void;
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
  model,
  onModelChange,
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
    // Two equal halves: the greeting sits at the bottom of the upper one, so
    // its baseline is the vertical centre whatever follows it. A visitor gets
    // no greeting: the blurb under it is what tells them what Hax is.
    <div className="mx-auto flex h-full w-full max-w-4xl flex-col p-4">
      <div className="flex flex-1 flex-col justify-end pb-4">
        {visitor ? null : (
          <h1 className="text-center font-serif text-display text-ink">
            {mounted ? greeting : "\u00a0"}
          </h1>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-4">
        {visitor ? (
          <p className="text-center text-lead text-ink-2">
            Hax is a chat that answers from your own documents. Try it without
            an account: ask about Hax itself.
          </p>
        ) : null}
        {visitor ? (
          <div className="flex flex-wrap justify-center gap-2">
            {chips.map((chip) => (
              <button
                key={chip}
                type="button"
                disabled={disabled}
                onClick={() => void onSend(chip)}
                className="rounded-full border border-border-control px-3 py-1.5 text-small text-ink hover:bg-surface-2 disabled:opacity-50"
              >
                {chip}
              </button>
            ))}
          </div>
        ) : null}
        <ChatInput
          onSend={onSend}
          disabled={disabled}
          model={model}
          onModelChange={onModelChange}
          visitor={visitor}
        />
        {error ? (
          <p className="text-small text-status-failed">{error}</p>
        ) : null}
      </div>
    </div>
  );
}
