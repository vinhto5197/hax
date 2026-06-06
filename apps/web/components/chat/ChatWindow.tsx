"use client";

import { useCallback, useState } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { useConversations } from "@/components/chat/ConversationsProvider";
import { MessageList } from "@/components/chat/MessageList";
import { useChat } from "@/hooks/useChat";
import type { ChatBackend } from "@/lib/chatApi";

export function ChatWindow({
  conversationId,
}: {
  conversationId: string | null;
}) {
  // Default agent-sdk: bills against the Max plan, not API credits (ADR 0002).
  const [backend, setBackend] = useState<ChatBackend>("agent-sdk");
  // From context (see ConversationsProvider); called after a turn to refresh
  // the sidebar.
  const { refresh } = useConversations();

  const handleConversationCreated = useCallback(
    (id: string) => {
      // Shallow URL update: linkable without remounting. router.replace would
      // cross the route segment and kill the in-flight stream.
      window.history.replaceState(null, "", `/chat/${id}`);
      refresh();
    },
    [refresh],
  );

  // One useChat owns all chat state; children get values via props.
  const { messages, isLoading, streamingContent, error, send } = useChat(
    backend,
    conversationId,
    handleConversationCreated,
    refresh,
  );

  return (
    <div className="mx-auto flex h-full w-full max-w-4xl flex-col gap-4 p-4">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">hax chat</h1>
          <p className="text-sm text-black/60 dark:text-white/60">
            Conversations are saved — pick one from the sidebar or start a new
            chat.
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
