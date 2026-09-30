"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { DemoLimitModal } from "@/components/chat/DemoLimitModal";
import { useConversations } from "@/components/chat/ConversationsProvider";
import { MessageList } from "@/components/chat/MessageList";
import { useChat } from "@/hooks/useChat";

// "" = server default (env LLM_MODEL). The Default label deliberately names no
// model — that's server-owned config and a name here would go stale.
const MODEL_OPTIONS = [
  { value: "", label: "Default" },
  { value: "claude-haiku-4-5", label: "Haiku" },
  { value: "claude-sonnet-4-6", label: "Sonnet" },
  { value: "claude-opus-4-8", label: "Opus" },
] as const;

// The demo: the landing page renders the chat in place for a visitor. The
// conversation gets no URL (a real request for /chat/* ends a demo — see
// proxy.ts), the first message is sent on mount, and there is no model choice
// (the API ignores it for visitors anyway).
export type DemoOptions = { initialPrompt: string };

export function ChatWindow({
  conversationId,
  demo,
}: {
  conversationId: string | null;
  demo?: DemoOptions;
}) {
  // Session identity = (conversationId, newChatNonce). The key forces a clean
  // remount when either changes — covering "+ New chat" from a lazy-created
  // conversation (same route, no prop change; the nonce is the only signal) —
  // and detaches any in-flight stream's closures so a stale send can't write
  // into the fresh session.
  const { newChatNonce, reportRoutedConversationId } = useConversations();
  // Report the routed id so startNewChat can tell whether a nonce bump is
  // needed (only when this is null — see ConversationsProvider).
  useEffect(() => {
    reportRoutedConversationId(conversationId);
  }, [conversationId, reportRoutedConversationId]);
  return (
    <ChatSession
      key={`${conversationId ?? "new"}:${newChatNonce}`}
      conversationId={conversationId}
      demo={demo}
    />
  );
}

function ChatSession({
  conversationId,
  demo,
}: {
  conversationId: string | null;
  demo?: DemoOptions;
}) {
  const [model, setModel] = useState("");
  // From context (see ConversationsProvider); called after a turn to refresh
  // the sidebar.
  const { refresh } = useConversations();

  const handleConversationCreated = useCallback(
    (id: string) => {
      // Shallow URL update — router.replace would cross the route segment and
      // kill the in-flight stream. A demo conversation gets no URL at all.
      if (!demo) window.history.replaceState(null, "", `/chat/${id}`);
      refresh();
    },
    [refresh, demo],
  );

  // One useChat owns all chat state; children get values via props.
  const {
    messages,
    isLoading,
    streamingContent,
    status,
    error,
    limited,
    send,
  } = useChat(
    conversationId,
    model || null,
    handleConversationCreated,
    refresh,
  );

  // The demo's first message, sent once on mount (the ref survives re-renders;
  // the key on ChatSession guarantees a fresh mount per demo).
  const sentInitial = useRef(false);
  useEffect(() => {
    if (!demo || sentInitial.current) return;
    sentInitial.current = true;
    void send(demo.initialPrompt);
  }, [demo, send]);

  return (
    <div className="mx-auto flex h-full w-full max-w-4xl flex-col gap-4 p-4">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">{demo ? "hax" : "hax chat"}</h1>
          <p className="text-sm text-black/60 dark:text-white/60">
            {demo ? (
              <>
                You&apos;re trying hax as a guest: a few turns, then{" "}
                <Link href="/signup" className="underline">
                  sign up
                </Link>{" "}
                to keep this conversation and use your own documents.
              </>
            ) : (
              <>
                Conversations are saved — pick one from the sidebar or start a
                new chat.
              </>
            )}
          </p>
        </div>
        {demo ? null : (
          <label className="flex flex-col gap-1 text-xs text-black/60 dark:text-white/60">
            Model
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
              disabled={isLoading}
              className="rounded-md border border-black/20 bg-transparent px-2 py-1 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              {MODEL_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>

      <MessageList
        messages={messages}
        isLoading={isLoading}
        streamingContent={streamingContent}
        status={status}
      />

      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}

      <ChatInput onSend={send} disabled={isLoading || limited} />

      {limited ? <DemoLimitModal /> : null}
    </div>
  );
}
