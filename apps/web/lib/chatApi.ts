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

// Dev: NEXT_PUBLIC_API_URL hits FastAPI directly (Next's dev rewrite buffers
// SSE). Prod: unset — same-origin via the reverse proxy. See ADR 0005.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// Response bodies are typed from the generated OpenAPI contract but not
// validated at runtime — we trust the first-party API.
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

// Ingestion is async (Celery): an upload returns 'pending' and the panel polls
// until it settles to ready|failed.
export async function listDocuments(): Promise<DocumentSummary[]> {
  const response = await fetch(`${API_BASE}/api/documents`);
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

export async function uploadDocument(file: File): Promise<DocumentSummary> {
  const form = new FormData();
  // Field name must match the FastAPI param (`file: UploadFile`) — a mismatch
  // is a runtime 422, not a compile error.
  form.append("file", file);
  // No explicit Content-Type: the browser must set the multipart boundary itself.
  const response = await fetch(`${API_BASE}/api/documents`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    // Surface FastAPI's `detail` — these errors are user-actionable.
    let detail = `API ${response.status}: ${response.statusText}`;
    try {
      // `detail` is a string for HTTPException but an array for 422 validation
      // errors; the array case falls through to the status message.
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body — keep the status-based message
    }
    throw new Error(detail);
  }
  return response.json();
}

// 204 on success (no body; response.ok covers it). A 404 means the doc was
// already gone (stale list, another tab) — the caller's goal holds, so treat it
// as success rather than surfacing a spurious error.
export async function deleteDocument(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/documents/${id}`, {
    method: "DELETE",
  });
  if (response.ok || response.status === 404) return;
  // Surface FastAPI's `detail` when present — statusText is empty under HTTP/2
  // behind the ALB, so a bare status is uninformative (mirrors uploadDocument).
  let detail = `API ${response.status}: ${response.statusText}`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // non-JSON error body — keep the status-based message
  }
  throw new Error(detail);
}

// Parsed result of one SSE event — a discriminated union so callers switch on
// `type`: prelude (conversation), token (chunk), tool-activity note (status),
// terminator (done), or unparseable/empty (ignore).
type StreamEvent =
  | { type: "conversation"; conversationId: string }
  | { type: "chunk"; content: string }
  | { type: "status"; status: string }
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
        status?: unknown;
      };
      if (typeof parsed.conversation_id === "string") {
        return { type: "conversation", conversationId: parsed.conversation_id };
      }
      if (typeof parsed.content === "string" && parsed.content.length > 0) {
        return { type: "chunk", content: parsed.content };
      }
      if (typeof parsed.status === "string" && parsed.status.length > 0) {
        return { type: "status", status: parsed.status };
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
  // Optional — omitting it just drops the tool-activity notes.
  onStatus?: (status: string) => void;
};

export async function streamChat(
  prompt: string,
  conversationId: string | null,
  handlers: StreamHandlers,
  model: string | null = null,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // Field names must match ChatRequest (hand-built body, not typed).
    // model null -> server default.
    body: JSON.stringify({ prompt, conversation_id: conversationId, model }),
  });

  if (!response.ok) {
    throw new Error(`API ${response.status}: ${response.statusText}`);
  }
  if (!response.body) {
    throw new Error("Streaming response body is missing.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  // Trailing partial event across reads (network reads ignore SSE boundaries).
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    // Transport EOF — the abnormal-finish path; a clean stream exits via [DONE].
    if (done) break;

    // stream:true holds back a partial multi-byte UTF-8 sequence until the
    // next read completes it.
    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const event of events) {
      const parsed = parseStreamEvent(event);
      if (parsed.type === "done") return;
      if (parsed.type === "conversation")
        handlers.onConversationId(parsed.conversationId);
      if (parsed.type === "chunk") handlers.onChunk(parsed.content);
      if (parsed.type === "status") handlers.onStatus?.(parsed.status);
    }
  }

  // Salvage a trailing event if the server closed without a final "\n\n".
  if (buffer.trim()) {
    const parsed = parseStreamEvent(buffer);
    if (parsed.type === "chunk") handlers.onChunk(parsed.content);
  }
}
