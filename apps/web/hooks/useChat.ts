"use client";

import { useCallback, useState } from "react";

import { type ChatMessage, streamChat } from "@/lib/chatApi";

type UseChatResult = {
  messages: ChatMessage[];
  isLoading: boolean;
  streamingContent: string;
  error: string | null;
  send: (text: string) => Promise<void>;
};

export function useChat(): UseChatResult {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const send = useCallback(
    async (text: string): Promise<void> => {
      const prompt = text.trim();
      if (!prompt || isLoading) return;

      // Functional setter: read latest committed state at update time, not
      // this render's closure snapshot.
      setMessages((prev) => [...prev, { role: "user", content: prompt }]);
      setIsLoading(true);
      // Belt-and-suspenders against leftover state if a prior turn errored
      // before its `finally` ran.
      setStreamingContent("");
      setError(null);

      try {
        let fullContent = "";
        await streamChat(prompt, (chunk) => {
          fullContent += chunk;
          setStreamingContent(fullContent);
        });

        // Skip commit if the stream produced no content — avoid an empty
        // phantom assistant bubble (e.g. refused/empty response).
        if (fullContent) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: fullContent },
          ]);
        }
      } catch (err) {
        // `throw` can yield any value; narrow before reading .message.
        const errMessage =
          err instanceof Error ? err.message : "Unable to get response.";
        setError(errMessage);
      } finally {
        // Runs on both success and error paths — UI can't get stuck "loading".
        setIsLoading(false);
        setStreamingContent("");
      }
    },
    // `send` reads `isLoading` — must be a dep so the closure refreshes
    // when it changes (else stale closure bug).
    [isLoading],
  );

  return { messages, isLoading, streamingContent, error, send };
}
