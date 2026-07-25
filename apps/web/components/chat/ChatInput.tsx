"use client";

import { type SubmitEvent, useState } from "react";

interface ChatInputProps {
  onSend: (text: string) => Promise<void>;
  disabled: boolean;
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [input, setInput] = useState("");

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();

    const prompt = input.trim();
    if (!prompt || disabled) return;

    // Clear optimistically — the input empties before the stream starts.
    setInput("");
    await onSend(prompt);
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <input
        type="text"
        className="flex-1 rounded-md border border-black/20 bg-transparent px-3 py-2 text-sm"
        placeholder="Type your prompt..."
        value={input}
        onChange={(event) => setInput(event.target.value)}
        disabled={disabled}
      />
      <button
        type="submit"
        className="rounded-md bg-foreground px-4 py-2 text-sm text-background disabled:cursor-not-allowed disabled:opacity-50"
        disabled={disabled || !input.trim()}
      >
        Send
      </button>
    </form>
  );
}
