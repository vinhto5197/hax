"use client";

import { ChatInput } from "@/components/chat/ChatInput";
import { MessageList } from "@/components/chat/MessageList";
import { useChat } from "@/hooks/useChat";

export function ChatWindow() {
  // Single useChat instance owns all chat state. Children receive values via
  // props — calling useChat elsewhere would create an independent chat.
  const { messages, isLoading, streamingContent, error, send } = useChat();

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-4xl flex-col gap-4 p-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">hax chat</h1>
        <p className="text-sm text-black/60 dark:text-white/60">
          Stateless chat: history lives in this browser tab only.
        </p>
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
