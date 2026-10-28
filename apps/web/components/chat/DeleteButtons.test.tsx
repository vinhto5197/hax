import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/chat/Sidebar";
import type { ConversationSummary, DocumentSummary } from "@/lib/chatApi";

const conversation: ConversationSummary = {
  id: "11111111-1111-1111-1111-111111111111",
  title: "Quarterly report",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const doc: DocumentSummary = {
  id: "22222222-2222-2222-2222-222222222222",
  filename: "notes.pdf",
  mime_type: "application/pdf",
  size_bytes: 1024,
  status: "ready",
  error: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

// Plain functions, not vi.fn: the config's mockReset would clear a queued
// return value before each test.
vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push: () => {}, replace: () => {}, refresh: () => {} }),
}));
vi.mock("next-auth/react", () => ({
  useSession: () => ({
    data: { user: { email: "a@example.com", name: "A" } },
    status: "authenticated",
  }),
  signOut: () => Promise.resolve(),
}));
vi.mock("@/components/chat/ConversationsProvider", () => ({
  useConversations: () => ({
    conversations: [conversation],
    loaded: true,
    refresh: () => {},
    newChatNonce: 0,
    startNewChat: () => {},
    reportRoutedConversationId: () => {},
  }),
}));
vi.mock("@/lib/chatApi", () => ({
  deleteConversation: () => Promise.resolve(),
  listDocuments: () => Promise.resolve([doc]),
  uploadDocument: () => Promise.resolve(doc),
  deleteDocument: () => Promise.resolve(),
  downloadDocument: () => Promise.resolve(),
}));
// The Sidebar test sees a stub panel; the DocumentsPanel test loads the real
// module past this mock with vi.importActual.
vi.mock("@/components/chat/DocumentsPanel", () => ({
  DocumentsPanel: () => null,
}));

beforeEach(() => {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
});

describe("delete buttons have a 44x44 hit area", () => {
  it("on a Sidebar conversation row", () => {
    render(<Sidebar />);
    const button = screen.getByRole("button", {
      name: "Delete Quarterly report",
    });
    expect(button).toHaveClass("min-h-11", "min-w-11");
  });

  it("on a DocumentsPanel document row", async () => {
    const { DocumentsPanel } = await vi.importActual<
      typeof import("@/components/chat/DocumentsPanel")
    >("@/components/chat/DocumentsPanel");
    render(<DocumentsPanel />);
    const button = await screen.findByRole("button", {
      name: "Delete notes.pdf",
    });
    expect(button).toHaveClass("min-h-11", "min-w-11");
  });
});
