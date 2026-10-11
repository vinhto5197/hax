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

// A new conversation's title is generated in the background and usually lands
// a moment after the first reply; the sidebar otherwise learns it only on the
// next turn. Re-read the list once a second, for at most this long, until it
// has a title. Never blocks sending.
const TITLE_POLL_MS = 1000;
const TITLE_POLL_TICKS = 10;

// A ChatWindow is mounted only once there is something to show: a routed
// conversation, or a new one whose first message (`initialPrompt`, from the
// NewChat screen) is sent on mount. `demo` marks the landing page's visitor
// chat: the conversation gets no URL (a real request for /chat/* ends a demo —
// see proxy.ts) and there is no model choice (the API ignores it for
// visitors anyway).
interface ChatWindowProps {
  conversationId: string | null;
  initialPrompt?: string;
  demo?: boolean;
}

export function ChatWindow({
  conversationId,
  initialPrompt,
  demo = false,
}: ChatWindowProps) {
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
      initialPrompt={initialPrompt}
      demo={demo}
    />
  );
}

function ChatSession({ conversationId, initialPrompt, demo }: ChatWindowProps) {
  const [model, setModel] = useState("");
  // From context (see ConversationsProvider); called after a turn to refresh
  // the sidebar.
  const { conversations, refresh } = useConversations();
  // The conversation this session created, if any: the one whose title is
  // awaited below. A demo has no sidebar, so it never sets this.
  const [createdId, setCreatedId] = useState<string | null>(null);

  const handleConversationCreated = useCallback(
    (id: string) => {
      // Shallow URL update — router.replace would cross the route segment and
      // kill the in-flight stream. A demo conversation gets no URL at all.
      if (!demo) {
        window.history.replaceState(null, "", `/chat/${id}`);
        setCreatedId(id);
      }
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

  const titled = conversations.some((c) => c.id === createdId && c.title);
  useEffect(() => {
    if (!createdId || isLoading || titled) return;
    let ticks = 0;
    const timer = setInterval(() => {
      ticks += 1;
      refresh();
      if (ticks >= TITLE_POLL_TICKS) clearInterval(timer);
    }, TITLE_POLL_MS);
    return () => clearInterval(timer);
  }, [createdId, isLoading, titled, refresh]);

  // A new conversation's first message, sent once on mount (the ref survives
  // re-renders; the key on ChatSession guarantees a fresh mount per session).
  const sentInitial = useRef(false);
  useEffect(() => {
    if (!initialPrompt || sentInitial.current) return;
    sentInitial.current = true;
    void send(initialPrompt);
  }, [initialPrompt, send]);

  return (
    <div className="flex h-full flex-col">
      <div
        className={`mx-auto flex w-full max-w-4xl items-center px-4 pt-4 ${
          demo ? "justify-start" : "justify-end"
        }`}
      >
        {demo ? (
          <p className="text-small text-ink-3">
            You&apos;re trying hax as a guest: a few turns, then{" "}
            <Link href="/signup" className="text-accent hover:underline">
              sign up
            </Link>{" "}
            to chat over your own documents.
          </p>
        ) : (
          <label className="flex items-center gap-2 text-caption text-ink-3">
            Model
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
              disabled={isLoading}
              className="rounded-control border border-border-control bg-surface-1 px-2 py-1 text-small text-ink disabled:cursor-not-allowed disabled:opacity-50"
            >
              {MODEL_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <MessageList
        messages={messages}
        isLoading={isLoading}
        streamingContent={streamingContent}
        status={status}
      />

      <div className="mx-auto w-full max-w-4xl px-4 pb-6 pt-2">
        {error ? (
          <p className="mb-2 text-small text-status-failed">{error}</p>
        ) : null}
        <ChatInput onSend={send} disabled={isLoading || limited} />
      </div>

      {limited ? <DemoLimitModal /> : null}
    </div>
  );
}
