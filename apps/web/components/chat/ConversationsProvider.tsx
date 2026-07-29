"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import { type ConversationSummary, listConversations } from "@/lib/chatApi";

// Shares the conversation list + refresh() between Sidebar and ChatWindow via
// context, mounted once in the chat layout so navigation doesn't refetch.
type ConversationsContextValue = {
  conversations: ConversationSummary[];
  // Stable identity — safe as an effect/callback dep.
  refresh: () => void;
  // Bumped by "+ New chat". A lazy-created conversation updates the URL via
  // history.replaceState, which Next's router never sees — so clicking
  // "+ New chat" from that state is a same-route navigation with NO prop
  // change. The nonce is the reset signal routing can't provide: ChatWindow
  // keys the session on it, forcing a clean remount.
  newChatNonce: number;
  startNewChat: () => void;
  // ChatWindow reports its routed conversationId here so startNewChat can skip
  // the bump when a REAL /chat/[id] is mounted — there, Link navigation resets
  // via the key's conversationId half, and bumping too would remount once with
  // the old id and fire a useless history fetch. (usePathname can't make this
  // call: it syncs with replaceState, so lazy and real look identical.)
  reportRoutedConversationId: (id: string | null) => void;
};

// null when read with no Provider above — useConversations() guards on it.
const ConversationsContext = createContext<ConversationsContextValue | null>(
  null,
);

export function ConversationsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [newChatNonce, setNewChatNonce] = useState(0);
  // Ref, not state: read imperatively at click time; nothing renders it.
  const routedIdRef = useRef<string | null>(null);

  const refresh = useCallback(() => {
    listConversations()
      .then(setConversations)
      .catch(() => {
        // A failed sidebar fetch shouldn't break the chat; leave the last list.
      });
  }, []);

  const reportRoutedConversationId = useCallback((id: string | null) => {
    routedIdRef.current = id;
  }, []);

  const startNewChat = useCallback(() => {
    // On a real /chat/[id], navigation alone resets the session (prop change ->
    // key change); bump only when the prop is null (lazy-created or fresh chat).
    if (routedIdRef.current === null) {
      setNewChatNonce((n) => n + 1);
    }
  }, []);

  // Initial load; refresh is stable so this runs once.
  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <ConversationsContext.Provider
      value={{
        conversations,
        refresh,
        newChatNonce,
        startNewChat,
        reportRoutedConversationId,
      }}
    >
      {children}
    </ConversationsContext.Provider>
  );
}

// Read the context. The guard fails loudly outside a Provider and narrows the
// return type from `... | null` to non-null.
export function useConversations(): ConversationsContextValue {
  const context = useContext(ConversationsContext);
  if (!context) {
    throw new Error(
      "useConversations must be used within a ConversationsProvider",
    );
  }
  return context;
}
