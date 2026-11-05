"use client";

import {
  type MouseEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { Markdown } from "@/components/chat/Markdown";
import { SourcesFooter } from "@/components/chat/SourcesFooter";
import { type ChatMessage } from "@/lib/chatApi";
import { REDUCED_MOTION } from "@/lib/media";
import { formatMessageTime } from "@/lib/time";

interface MessageListProps {
  messages: ChatMessage[];
  isLoading: boolean;
  streamingContent: string;
  // Live tool-activity note ("Searching documents…"); null when no tool runs.
  status: string | null;
  // A reply is being written on the server that this tab is not streaming.
  stillAnswering?: boolean;
}

// Follows the conversation: the list is the scroll container, and nothing
// else moves it, so new content would otherwise land out of view.
const STICK_THRESHOLD_PX = 64;

// A send's optimistic turn, or a re-read that grew and ends on a question:
// either way the conversation is moving at the bottom, so the follow returns.
function isNewUserTurn(prevLength: number, messages: ChatMessage[]): boolean {
  return (
    messages.length > prevLength &&
    messages[messages.length - 1].role === "user"
  );
}

// Copies the raw Markdown of a message (its stored `content`), not the
// rendered text.
function CopyButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    // The clipboard can refuse (permission, insecure context); a click handler
    // must not leave an unhandled rejection (same contract as DataTable's copy).
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label="Copy message"
      className="rounded p-0.5 text-ink-3 hover:bg-surface-2 hover:text-ink"
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        {copied ? (
          <path d="M3 8.5l3 3 7-7" />
        ) : (
          <>
            <rect x="5" y="5" width="9" height="9" rx="1.5" />
            <path d="M3 11V3h8" />
          </>
        )}
      </svg>
    </button>
  );
}

export function MessageList({
  messages,
  isLoading,
  streamingContent,
  status,
  stillAnswering = false,
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // Whether the reader was at the bottom BEFORE this render's content landed;
  // measured in the layout phase, so the previous frame's scroll position is
  // still what the browser reports.
  const stuckRef = useRef(true);
  const lastTopRef = useRef(0);
  const prevLengthRef = useRef(messages.length);
  // Mirrors !stuckRef.current for rendering; set only when the follow flips,
  // since a render per scroll event re-renders every Markdown in the thread.
  const [released, setReleased] = useState(false);
  const [prevLength, setPrevLength] = useState(messages.length);
  if (messages.length !== prevLength) {
    setPrevLength(messages.length);
    if (isNewUserTurn(prevLength, messages)) setReleased(false);
  }

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (isNewUserTurn(prevLengthRef.current, messages)) stuckRef.current = true;
    prevLengthRef.current = messages.length;
    if (stuckRef.current) el.scrollTop = el.scrollHeight;
    // The browser also clamps scrollTop when content shrinks (the status line
    // leaving); record what it settled on so that clamp never reads as the
    // user scrolling up.
    lastTopRef.current = el.scrollTop;
  }, [messages, streamingContent, status, stillAnswering]);

  // The scroller shrinking (viewport resize, the composer growing) leaves a
  // stuck reader scrolled up from the bottom with no content change to re-pin.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      if (!stuckRef.current) return;
      el.scrollTop = el.scrollHeight;
      lastTopRef.current = el.scrollTop;
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

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
      if (stuckRef.current) {
        stuckRef.current = false;
        setReleased(true);
      }
    } else if (fromBottom <= STICK_THRESHOLD_PX) {
      if (!stuckRef.current) {
        stuckRef.current = true;
        setReleased(false);
      }
    }
    lastTopRef.current = top;
  }

  function jumpToLatest(event: MouseEvent<HTMLButtonElement>) {
    const el = scrollRef.current;
    if (!el) return;
    stuckRef.current = true;
    setReleased(false);
    const reduce = window.matchMedia(REDUCED_MOTION).matches;
    // Relies on a content change's pin (a scrollTop assignment) aborting this
    // smooth scroll, per CSSOM; an engine that kept animating would end short
    // of the new bottom, and its next scroll event would release the follow.
    el.scrollTo({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" });
    // The button unmounts once the view is back at the bottom, which would drop
    // keyboard focus to <body>. A click with detail 0 came from Enter or Space
    // (or assistive tech), never a pointer: focusing the composer on a phone
    // tap would open the on-screen keyboard. Looked up by its label because
    // the composer lives in ChatInput, outside this list.
    if (event.detail === 0) {
      document
        .querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')
        ?.focus();
    }
  }

  return (
    <>
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-1 overflow-y-auto"
      >
        <div className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6">
          {messages.map((message, index) => {
            const isUser = message.role === "user";
            const time = message.created_at ? (
              <time dateTime={message.created_at}>
                {formatMessageTime(message.created_at)}
              </time>
            ) : null;
            return (
              // Index keys: the list changes at its end, or is replaced whole
              // by a re-read; a row's local state may carry to the message
              // that replaces it.
              <div
                key={`${message.role}-${index}`}
                className={`group flex flex-col ${isUser ? "items-end" : "items-start"}`}
              >
                {isUser ? (
                  <div className="max-w-[85%] rounded-card bg-bubble-user px-4 py-2.5 text-body whitespace-pre-wrap wrap-break-word text-bubble-user-ink">
                    {message.content}
                  </div>
                ) : (
                  <div className="w-full min-w-0 text-body text-ink wrap-break-word">
                    <Markdown content={message.content} />
                    {message.sources?.length ? (
                      <SourcesFooter sources={message.sources} />
                    ) : null}
                  </div>
                )}
                {/* Hover-only slot of fixed height: always laid out, so showing
                  it never moves the turns below. */}
                <div className="mt-1 flex h-4 items-center gap-1.5 text-caption text-ink-3 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 touch:opacity-100">
                  {isUser ? (
                    <>
                      <CopyButton content={message.content} />
                      {time}
                    </>
                  ) : (
                    <>
                      {time}
                      <CopyButton content={message.content} />
                    </>
                  )}
                </div>
              </div>
            );
          })}

          {/* Live turn while streaming; on finish useChat commits the content
            into `messages` and clears this — a seamless swap. */}
          {streamingContent ? (
            <div className="w-full min-w-0 text-body text-ink wrap-break-word">
              <Markdown content={streamingContent} />
            </div>
          ) : null}

          {/* Activity indicator: "Still answering…" while the reply is written
            on the server without this tab streaming it; else the live tool
            status (even mid-stream), else the generic line in the gap before
            the first chunk. */}
          {stillAnswering || (isLoading && (status || !streamingContent)) ? (
            <p
              role="status"
              aria-live="polite"
              className="animate-pulse text-small text-ink-3"
            >
              {stillAnswering
                ? "Still answering…"
                : (status ?? "Assistant is thinking...")}
            </p>
          ) : null}
        </div>
      </div>
      {/* Outside the scroller, so appearing never changes the scrollHeight the
        follow measures. No z-index: later overlays without one (the demo-limit
        modal) must still paint above it. */}
      <div className="relative h-0">
        {released ? (
          <button
            type="button"
            aria-label="Jump to latest"
            onClick={jumpToLatest}
            className="absolute bottom-4 left-1/2 flex size-9 -translate-x-1/2 items-center justify-center rounded-full border border-border bg-surface-1 text-ink-2 shadow-md hover:bg-surface-2 hover:text-ink"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M8 3v10M3.5 8.5 8 13l4.5-4.5" />
            </svg>
          </button>
        ) : null}
      </div>
    </>
  );
}
