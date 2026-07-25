"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

import { type ConversationSummary, listConversations } from "@/lib/chatApi";

// Shares the conversation list + refresh() between Sidebar and ChatWindow via
// context, mounted once in the chat layout so navigation doesn't refetch.
type ConversationsContextValue = {
  conversations: ConversationSummary[];
  // Stable identity — safe as an effect/callback dep.
  refresh: () => void;
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

  const refresh = useCallback(() => {
    listConversations()
      .then(setConversations)
      .catch(() => {
        // A failed sidebar fetch shouldn't break the chat; leave the last list.
      });
  }, []);

  // Initial load; refresh is stable so this runs once.
  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <ConversationsContext.Provider value={{ conversations, refresh }}>
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
