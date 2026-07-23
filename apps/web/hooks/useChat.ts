"use client";

import { useCallback, useEffect, useState } from "react";

import { type ChatMessage, getConversation, streamChat } from "@/lib/chatApi";

type UseChatResult = {
  messages: ChatMessage[];
  isLoading: boolean;
  streamingContent: string;
  // Live tool-activity note from the agentic harness ("Searching documents…"),
  // or null when no tool is running. Transient — never part of the transcript.
  status: string | null;
  error: string | null;
  send: (text: string) => Promise<void>;
};

// Owns all chat state for the current conversation: transcript, streaming
// buffer, tool status, loading/error, and send. Optional callbacks report
// lazy-create and turn-completion so the hook stays decoupled from routing/
// sidebar concerns. `model` null -> server default (env LLM_MODEL).
export function useChat(
  conversationId: string | null,
  model: string | null,
  onConversationCreated?: (id: string) => void,
  onTurnComplete?: () => void,
): UseChatResult {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The id sends target. Starts from the route prop; updated when a lazy-create
  // returns a new id, so follow-up turns hit the same conversation even though
  // the route prop stayed null (the URL was updated shallowly, not navigated).
  const [activeId, setActiveId] = useState<string | null>(conversationId);

  // Load history when the route's conversation changes (opening an existing
  // conversation, or a page refresh). A new chat (null) starts empty.
  useEffect(() => {
    setActiveId(conversationId);
    if (!conversationId) {
      setMessages([]);
      return;
    }
    // Race guard: each effect run owns this flag; the cleanup below flips it
    // when the route changes, so a slower earlier fetch can't land last and
    // overwrite the conversation we've since navigated to.
    let cancelled = false;
    getConversation(conversationId)
      .then((conv) => {
        if (cancelled) return;
        setMessages(
          // role is `string` in the generated type but constrained to
          // user/assistant by a DB CHECK; safe to narrow.
          conv.messages.map((m) => ({
            role: m.role as ChatMessage["role"],
            content: m.content,
          })),
        );
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load this conversation.");
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  const send = useCallback(
    async (text: string): Promise<void> => {
      const prompt = text.trim();
      // Ignore empty input and block a second send while one is streaming.
      if (!prompt || isLoading) return;

      // Optimistically show the user's message before the network round-trip.
      setMessages((prev) => [...prev, { role: "user", content: prompt }]);
      setIsLoading(true);
      setStreamingContent("");
      setError(null);

      try {
        // Source of truth for the final assistant message. streamingContent
        // (state) mirrors this for live rendering, but state is async/batched —
        // fullContent accumulates synchronously so we can commit it below.
        let fullContent = "";
        await streamChat(
          prompt,
          activeId,
          {
            onConversationId: (id) => {
              // Adopt the server-created id, set-once: the functional updater
              // keeps the current id if we already have one, so a late prelude
              // can't overwrite activeId after we've navigated to another
              // conversation (which would misroute the next send).
              setActiveId((current) => current ?? id);
              // Fires only on a new chat's first turn (closure activeId is null
              // only then) — let the caller make the URL linkable + refresh.
              if (!activeId) onConversationCreated?.(id);
            },
            onChunk: (chunk) => {
              fullContent += chunk;
              setStreamingContent(fullContent);
              // Text arriving means the tool the status announced has finished.
              setStatus(null);
            },
            // A new tool call announced — show it until text resumes (a later
            // tool call in the same turn simply replaces it).
            onStatus: setStatus,
          },
          model,
        );

        if (fullContent) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: fullContent },
          ]);
        }
        // Let the caller refresh the sidebar (new conversation / updated order).
        onTurnComplete?.();
      } catch (err) {
        const errMessage =
          err instanceof Error ? err.message : "Unable to get response.";
        setError(errMessage);
      } finally {
        // Always clear: the assistant text now lives in messages, so the
        // streaming buffer must empty or it would render twice.
        setIsLoading(false);
        setStreamingContent("");
        setStatus(null);
      }
    },
    [isLoading, model, activeId, onConversationCreated, onTurnComplete],
  );

  return { messages, isLoading, streamingContent, status, error, send };
}
