type ChatRole = "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

type StreamEvent =
  | { type: "chunk"; content: string }
  | { type: "done" }
  | { type: "ignore" };

function parseStreamEvent(rawEvent: string): StreamEvent {
  for (const line of rawEvent.split("\n")) {
    if (!line.startsWith("data:")) continue;

    const data = line.slice(5).trim();
    if (!data) continue;
    if (data === "[DONE]") return { type: "done" };

    try {
      const parsed = JSON.parse(data) as { content?: unknown };
      if (typeof parsed.content === "string" && parsed.content.length > 0) {
        return { type: "chunk", content: parsed.content };
      }
    } catch {
      return { type: "ignore" };
    }
  }

  return { type: "ignore" };
}

export async function streamChat(
  prompt: string,
  onChunk: (content: string) => void,
): Promise<void> {
  // Same-origin path. In dev, Next rewrites proxies it to FastAPI on :8000;
  // in prod, the ALB routes /api/* to the FastAPI service. No CORS either way.
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });

  if (!response.ok) {
    throw new Error(`API ${response.status}: ${response.statusText}`);
  }
  if (!response.body) {
    throw new Error("Streaming response body is missing.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  // Holds the trailing partial event across reads (network reads don't respect
  // SSE event boundaries).
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    // `stream: true` defers emitting bytes that may be a partial multi-byte
    // UTF-8 sequence, until the next read completes them.
    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const event of events) {
      const parsed = parseStreamEvent(event);
      if (parsed.type === "done") return;
      if (parsed.type === "chunk") onChunk(parsed.content);
    }
  }

  // Salvage a trailing event if the server closed without a final "\n\n".
  if (buffer.trim()) {
    const parsed = parseStreamEvent(buffer);
    if (parsed.type === "chunk") onChunk(parsed.content);
  }
}
