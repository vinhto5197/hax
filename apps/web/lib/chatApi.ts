type ChatRole = "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

// Which FastAPI route handles the request. Both speak the same SSE wire
// format; only the LLM backend differs (see ADR 0002).
export type ChatBackend = "agent-sdk" | "anthropic";

const BACKEND_PATHS: Record<ChatBackend, string> = {
  "agent-sdk": "/api/chat-agent-sdk",
  anthropic: "/api/chat",
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
  backend: ChatBackend = "agent-sdk",
): Promise<void> {
  // In dev, NEXT_PUBLIC_API_URL points at FastAPI directly (Next's dev
  // rewrite buffers SSE responses and kills streaming). In prod, the env
  // var is unset, the fetch is same-origin, and the ALB routes /api/* to
  // FastAPI.
  const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
  const response = await fetch(`${BASE_URL}${BACKEND_PATHS[backend]}`, {
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
