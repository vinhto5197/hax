"use client";

import { useState } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { MessageList } from "@/components/chat/MessageList";
import { useChat } from "@/hooks/useChat";
import type { ChatBackend } from "@/lib/chatApi";

export function ChatWindow() {
  // Default to agent-sdk: bills against the Max subscription's usage cap
  // instead of API credits. See ADR 0002 for the tradeoffs.
  const [backend, setBackend] = useState<ChatBackend>("agent-sdk");

  // Single useChat instance owns all chat state. Children receive values via
  // props — calling useChat elsewhere would create an independent chat.
  const { messages, isLoading, streamingContent, error, send } =
    useChat(backend);

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-4xl flex-col gap-4 p-4">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">hax chat</h1>
          <p className="text-sm text-black/60 dark:text-white/60">
            Stateless chat: history lives in this browser tab only.
          </p>
        </div>
        <label className="flex flex-col gap-1 text-xs text-black/60 dark:text-white/60">
          Backend
          <select
            value={backend}
            onChange={(event) => setBackend(event.target.value as ChatBackend)}
            disabled={isLoading}
            className="rounded-md border border-black/20 bg-transparent px-2 py-1 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option value="agent-sdk">Claude Agent SDK (Max)</option>
            <option value="anthropic">Anthropic SDK (API key)</option>
          </select>
        </label>
      </header>

      <MessageList
        messages={messages}
        isLoading={isLoading}
        streamingContent={streamingContent}
      />

      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}

      <ChatInput onSend={send} disabled={isLoading} />
    </div>
  );
}
