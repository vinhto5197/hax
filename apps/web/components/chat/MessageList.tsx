"use client";

import { useLayoutEffect, useRef } from "react";

import { Markdown } from "@/components/chat/Markdown";
import { SourcesFooter } from "@/components/chat/SourcesFooter";
import { type ChatMessage } from "@/lib/chatApi";

interface MessageListProps {
  messages: ChatMessage[];
  isLoading: boolean;
  streamingContent: string;
  // Live tool-activity note ("Searching documents…"); null when no tool runs.
  status: string | null;
}

// Follows the conversation: the list is the scroll container, and nothing
// else moves it, so new content would otherwise land out of view.
const STICK_THRESHOLD_PX = 64;

export function MessageList({
  messages,
  isLoading,
  streamingContent,
  status,
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // Whether the reader was at the bottom BEFORE this render's content landed;
  // measured in the layout phase, so the previous frame's scroll position is
  // still what the browser reports.
  const stuckRef = useRef(true);
  const lastTopRef = useRef(0);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (stuckRef.current) el.scrollTop = el.scrollHeight;
    // The browser also clamps scrollTop when content shrinks (the status line
    // leaving); record what it settled on so that clamp never reads as the
    // user scrolling up.
    lastTopRef.current = el.scrollTop;
  }, [messages, streamingContent, status]);

  // An upward scroll that leaves the bottom releases the follow at once (one
  // wheel notch is less than the re-engage distance, so a threshold alone
  // would keep dragging a rereading user down); scrolling back near the
  // bottom re-engages it. A clamp from shrinking content moves up but stays
  // at the bottom, so the distance check keeps it from releasing.
  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const top = el.scrollTop;
    const fromBottom = el.scrollHeight - top - el.clientHeight;
    if (top < lastTopRef.current && fromBottom > STICK_THRESHOLD_PX) {
      stuckRef.current = false;
    } else if (fromBottom <= STICK_THRESHOLD_PX) {
      stuckRef.current = true;
    }
    lastTopRef.current = top;
  }

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="flex-1 overflow-y-auto rounded-lg border border-black/10 p-4"
    >
      <div className="space-y-3">
        {messages.map((message, index) => {
          const isUser = message.role === "user";
          return (
            // Index keys are safe here — messages are append-only (no reorders
            // or deletes), so React's positional matching never breaks.
            <div
              key={`${message.role}-${index}`}
              className={`flex ${isUser ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                  isUser
                    ? "bg-foreground text-background"
                    : "bg-black/5 text-foreground dark:bg-white/10"
                }`}
              >
                {isUser ? (
                  message.content
                ) : (
                  <>
                    <Markdown content={message.content} />
                    {message.sources?.length ? (
                      <SourcesFooter sources={message.sources} />
                    ) : null}
                  </>
                )}
              </div>
            </div>
          );
        })}

        {/* Live bubble while streaming; on finish useChat commits the content
            into `messages` and clears this — a seamless swap. */}
        {streamingContent ? (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-lg bg-black/5 px-3 py-2 text-sm text-foreground dark:bg-white/10">
              <Markdown content={streamingContent} />
            </div>
          </div>
        ) : null}

        {/* Activity indicator: the live tool status (even mid-stream), else the
            generic line in the gap before the first chunk. */}
        {isLoading && (status || !streamingContent) ? (
          <p className="animate-pulse text-sm text-black/60 dark:text-white/60">
            {status ?? "Assistant is thinking..."}
          </p>
        ) : null}
      </div>
    </div>
  );
}
