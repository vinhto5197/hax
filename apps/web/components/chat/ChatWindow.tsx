"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { DemoLimitModal } from "@/components/chat/DemoLimitModal";
import { EvolvingNotice } from "@/components/EvolvingNotice";
import { useConversations } from "@/components/chat/ConversationsProvider";
import { MessageList } from "@/components/chat/MessageList";
import { useChat } from "@/hooks/useChat";

// A new conversation's title is generated in the background and usually lands
// a moment after the first reply; the sidebar otherwise learns it only on the
// next turn. Re-read the list once a second, for at most this long, until it
// has a title. Never blocks sending.
const TITLE_POLL_MS = 1000;
const TITLE_POLL_TICKS = 10;

// A ChatWindow is mounted only once there is something to show: a routed
// conversation, or a new one whose first message (`initialPrompt`, from the
// NewChat screen) is sent on mount, carrying the model chosen on that screen
// (`initialModel`). `demo` marks the landing page's visitor chat: the
// conversation gets no URL (a real request for /chat/* ends a demo — see
// proxy.ts) and there is no model choice (the API pins a visitor to the
// default model).
interface ChatWindowProps {
  conversationId: string | null;
  initialPrompt?: string;
  initialModel?: string;
  demo?: boolean;
}

export function ChatWindow({
  conversationId,
  initialPrompt,
  initialModel,
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
      initialModel={initialModel}
      demo={demo}
    />
  );
}

function ChatSession({
  conversationId,
  initialPrompt,
  initialModel,
  demo,
}: ChatWindowProps) {
  const [model, setModel] = useState(initialModel ?? "");
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

  const {
    messages,
    isLoading,
    streamingContent,
    status,
    error,
    limited,
    stillAnswering,
    restoreDraft,
    send,
  } = useChat(
    conversationId,
    model || null,
    handleConversationCreated,
    refresh,
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
      {demo ? <EvolvingNotice /> : null}
      {demo ? (
        <p className="mx-auto w-full max-w-4xl px-4 pt-4 text-small text-ink-3">
          You&apos;re trying Hax as a guest: a few turns, then{" "}
          <Link
            href="/signup"
            className="text-accent underline underline-offset-2"
          >
            sign up
          </Link>{" "}
          to chat over your own documents. Already have an account?{" "}
          <Link
            href="/login"
            className="text-accent underline underline-offset-2"
          >
            Log in
          </Link>
          .
        </p>
      ) : null}

      <MessageList
        messages={messages}
        isLoading={isLoading}
        streamingContent={streamingContent}
        status={status}
        stillAnswering={stillAnswering}
      />

      <div className="mx-auto w-full max-w-4xl px-4 pb-6 pt-2">
        {error ? (
          <p role="alert" className="mb-2 text-small text-status-failed">
            {error}
          </p>
        ) : null}
        <ChatInput
          onSend={send}
          draft={restoreDraft}
          disabled={isLoading || limited}
          model={demo ? undefined : model}
          onModelChange={demo ? undefined : setModel}
          visitor={demo}
        />
      </div>

      {limited ? <DemoLimitModal /> : null}
    </div>
  );
}
