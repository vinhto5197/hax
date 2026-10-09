"use client";

import { useCallback, useEffect, useState } from "react";

import {
  type ChatMessage,
  DemoLimitError,
  getConversation,
  type Source,
  streamChat,
} from "@/lib/chatApi";

type UseChatResult = {
  messages: ChatMessage[];
  isLoading: boolean;
  streamingContent: string;
  // Live tool-activity note from the agentic harness ("Searching documents…"),
  // or null when no tool is running. Transient — never part of the transcript.
  status: string | null;
  error: string | null;
  // An anonymous visitor hit the demo cap; the caller shows the sign-up prompt.
  limited: boolean;
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
  const [limited, setLimited] = useState(false);
  // The id sends target. Starts from the route prop; updated when a lazy-create
  // returns a new id, so follow-up turns hit the same conversation even though
  // the route prop stayed null (the URL was updated shallowly, not navigated).
  const [activeId, setActiveId] = useState<string | null>(conversationId);

  // Load history when the route's conversation changes. A new chat (null)
  // starts empty by construction — the session is keyed per conversation, so
  // it is always a fresh mount — and must NOT be cleared here: an effect can
  // run twice on mount (strict mode), and a second clear would wipe the
  // optimistic first turn a mount-send had placed.
  useEffect(() => {
    setActiveId(conversationId);
    if (!conversationId) return;
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
            // null (user rows, sourceless turns) and undefined both mean no footer.
            sources: m.sources ?? undefined,
            created_at: m.created_at,
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
      setMessages((prev) => [
        ...prev,
        { role: "user", content: prompt, created_at: new Date().toISOString() },
      ]);
      setIsLoading(true);
      setStreamingContent("");
      setError(null);

      // Source of truth for the final assistant message. streamingContent
      // (state) mirrors this for live rendering, but state is async/batched —
      // fullContent accumulates synchronously so the finally can commit it.
      let fullContent = "";
      // Provenance for this turn. The server dedups only what it persists
      // and forwards every event unchanged, so two searches that hit the
      // same chunk arrive twice here; dedup by the server's key, first-seen
      // order, so the live bubble matches the reloaded one.
      const sources = new Map<string, Source>();
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
            onSources: (batch) => {
              for (const s of batch) {
                const key = `${s.document_id}:${s.chunk_idx}`;
                if (!sources.has(key)) sources.set(key, s);
              }
            },
          },
          model,
        );

        // Let the caller refresh the sidebar (new conversation / updated order).
        onTurnComplete?.();
      } catch (err) {
        if (err instanceof DemoLimitError) {
          // Refused before anything was persisted: drop the optimistic turn
          // so the view matches the server.
          setMessages((prev) => prev.slice(0, -1));
          setLimited(true);
          return;
        }
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
            {
              role: "assistant",
              content: fullContent,
              sources: sources.size ? [...sources.values()] : undefined,
              created_at: new Date().toISOString(),
            },
          ]);
        }
        setIsLoading(false);
        setStreamingContent("");
        setStatus(null);
      }
    },
    [isLoading, model, activeId, onConversationCreated, onTurnComplete],
  );

  return {
    messages,
    isLoading,
    streamingContent,
    status,
    error,
    limited,
    send,
  };
}
