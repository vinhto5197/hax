import { Markdown } from "@/components/chat/Markdown";
import { type ChatMessage } from "@/lib/chatApi";

interface MessageListProps {
  messages: ChatMessage[];
  isLoading: boolean;
  streamingContent: string;
}

export function MessageList({
  messages,
  isLoading,
  streamingContent,
}: MessageListProps) {
  return (
    <div className="flex-1 overflow-y-auto rounded-lg border border-black/10 p-4">
      {messages.length === 0 && !streamingContent ? (
        <p className="text-sm text-black/60 dark:text-white/60">
          Start chatting by entering a prompt below.
        </p>
      ) : null}

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
                  <Markdown content={message.content} />
                )}
              </div>
            </div>
          );
        })}

        {/* Live "ghost" bubble while streaming. When the stream finishes,
            useChat commits the content into `messages` and clears
            streamingContent — visually seamless transition. */}
        {streamingContent ? (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-lg bg-black/5 px-3 py-2 text-sm text-foreground dark:bg-white/10">
              <Markdown content={streamingContent} />
            </div>
          </div>
        ) : null}

        {/* Shown only in the gap between request-sent and first-chunk-arrived.
            Once chunks arrive, streamingContent is truthy and this hides. */}
        {isLoading && !streamingContent ? (
          <p className="text-sm text-black/60 dark:text-white/60">
            Assistant is thinking...
          </p>
        ) : null}
      </div>
    </div>
  );
}
