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

  // Load history when the route's conversation changes; a new chat (null)
  // starts empty.
  useEffect(() => {
    setActiveId(conversationId);
    if (!conversationId) {
      setMessages([]);
      return;
    }
    // Race guard: each run owns this flag; cleanup flips it on navigation so a
    // slower earlier fetch can't overwrite the conversation we moved to.
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

      // Source of truth for the final assistant message. streamingContent
      // (state) mirrors this for live rendering, but state is async/batched —
      // fullContent accumulates synchronously so the finally can commit it.
      let fullContent = "";
      try {
        await streamChat(
          prompt,
          activeId,
          {
            onConversationId: (id) => {
              // Set-once: a late prelude can't overwrite activeId after we've
              // navigated elsewhere (which would misroute the next send).
              setActiveId((current) => current ?? id);
              // Only fires on a new chat's first turn (activeId null only then).
              if (!activeId) onConversationCreated?.(id);
            },
            onChunk: (chunk) => {
              fullContent += chunk;
              setStreamingContent(fullContent);
              // Text arriving means the announced tool has finished.
              setStatus(null);
            },
            onStatus: setStatus,
          },
          model,
        );

        // Let the caller refresh the sidebar (new conversation / updated order).
        onTurnComplete?.();
      } catch (err) {
        const errMessage =
          err instanceof Error ? err.message : "Unable to get response.";
        setError(errMessage);
      } finally {
        // Commit whatever streamed — on success AND error — so the client view
        // matches the server, which persists partial turns too. Then clear the
        // streaming buffer or the text would render twice.
        if (fullContent) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: fullContent },
          ]);
        }
        setIsLoading(false);
        setStreamingContent("");
        setStatus(null);
      }
    },
    [isLoading, model, activeId, onConversationCreated, onTurnComplete],
  );

  return { messages, isLoading, streamingContent, status, error, send };
}
