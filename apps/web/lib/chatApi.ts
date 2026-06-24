import type { components } from "@/lib/openapi";

type ChatRole = "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

// Response shapes generated from the FastAPI OpenAPI spec (see `make types`).
export type ConversationSummary = components["schemas"]["ConversationOut"];
export type ConversationDetail = components["schemas"]["ConversationDetailOut"];
export type DocumentSummary = components["schemas"]["DocumentOut"];

// Which FastAPI route handles the request. Both speak the same SSE wire
// format; only the LLM backend differs (see ADR 0002).
export type ChatBackend = "agent-sdk" | "anthropic";

const BACKEND_PATHS: Record<ChatBackend, string> = {
  "agent-sdk": "/api/chat-agent-sdk",
  anthropic: "/api/chat",
};

// In dev, NEXT_PUBLIC_API_URL points at FastAPI directly (Next's dev rewrite
// buffers SSE responses and kills streaming). In prod it's unset, requests are
// same-origin, and the ALB routes /api/* to FastAPI. See ADR 0005.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// Conversation fetches. Response bodies are typed from the generated OpenAPI
// contract but not validated at runtime — we trust the first-party API.
export async function listConversations(): Promise<ConversationSummary[]> {
  const response = await fetch(`${API_BASE}/api/conversations`);
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const response = await fetch(`${API_BASE}/api/conversations/${id}`);
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

// Document upload / listing. The uploaded doc is ingested synchronously, so the
// returned row already carries its final status (ready | failed).
export async function listDocuments(): Promise<DocumentSummary[]> {
  const response = await fetch(`${API_BASE}/api/documents`);
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

export async function uploadDocument(file: File): Promise<DocumentSummary> {
  const form = new FormData();
  // The field name "file" must match the FastAPI param (`file: UploadFile`); a
  // mismatch is a runtime 422, not a compile error — an untyped string contract.
  form.append("file", file);
  // No Content-Type header on purpose: a FormData body makes the browser set
  // `multipart/form-data; boundary=…` itself. Setting it by hand omits the
  // boundary, and the server can't split the parts.
  const response = await fetch(`${API_BASE}/api/documents`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    // Surface FastAPI's `detail` (e.g. "only .txt and .md files are supported")
    // instead of a bare status, since these errors are user-actionable.
    let detail = `API ${response.status}: ${response.statusText}`;
    try {
      // FastAPI's `detail` is a string for HTTPException (400/413) but an array
      // of error objects for 422 validation failures — typed `unknown` so we
      // must narrow; the array case falls through to the status message.
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body — keep the status-based message
    }
    throw new Error(detail);
  }
  return response.json();
}

// Parsed result of one SSE event — a discriminated union so callers switch on
// `type`: prelude (conversation), token (chunk), terminator (done), or
// unparseable/empty (ignore).
type StreamEvent =
  | { type: "conversation"; conversationId: string }
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
      // Untrusted network JSON: fields are `unknown` so the compiler forces the
      // runtime typeof checks below — a malformed event then falls through to
      // `ignore` rather than being trusted as a string.
      const parsed = JSON.parse(data) as {
        content?: unknown;
        conversation_id?: unknown;
      };
      // Prelude event: the server tells us which conversation this turn belongs
      // to (a freshly created id on the first turn of a new chat).
      if (typeof parsed.conversation_id === "string") {
        return { type: "conversation", conversationId: parsed.conversation_id };
      }
      if (typeof parsed.content === "string" && parsed.content.length > 0) {
        return { type: "chunk", content: parsed.content };
      }
    } catch {
      return { type: "ignore" };
    }
  }

  return { type: "ignore" };
}

export type StreamHandlers = {
  onConversationId: (id: string) => void;
  onChunk: (content: string) => void;
};

export async function streamChat(
  prompt: string,
  conversationId: string | null,
  handlers: StreamHandlers,
  backend: ChatBackend = "agent-sdk",
): Promise<void> {
  const response = await fetch(`${API_BASE}${BACKEND_PATHS[backend]}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // These field names must match the FastAPI `ChatRequest` schema; a mismatch
    // is a runtime 422, not a compile error (the body is hand-built, not typed).
    body: JSON.stringify({ prompt, conversation_id: conversationId }),
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
    // Transport EOF — ends the loop, and the path for an abnormal finish
    // (disconnect/error with no [DONE]). A clean stream returns via the [DONE]
    // sentinel below before we ever reach this.
    if (done) break;

    // `stream: true` defers emitting bytes that may be a partial multi-byte
    // UTF-8 sequence, until the next read completes them.
    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const event of events) {
      const parsed = parseStreamEvent(event);
      // [DONE] sentinel: clean app-level completion — the normal exit.
      if (parsed.type === "done") return;
      if (parsed.type === "conversation")
        handlers.onConversationId(parsed.conversationId);
      if (parsed.type === "chunk") handlers.onChunk(parsed.content);
    }
  }

  // Salvage a trailing event if the server closed without a final "\n\n".
  if (buffer.trim()) {
    const parsed = parseStreamEvent(buffer);
    if (parsed.type === "chunk") handlers.onChunk(parsed.content);
  }
}
