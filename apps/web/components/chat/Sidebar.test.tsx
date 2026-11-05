import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/chat/Sidebar";
import type { ConversationSummary } from "@/lib/chatApi";
import { stubMatchMedia } from "@/test-utils/matchMedia";

const conversation: ConversationSummary = {
  id: "11111111-1111-1111-1111-111111111111",
  title: "Quarterly report",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

// A mutable holder read at call time, not vi.fn: the config's mockReset
// would clear a queued return value before each test.
const list = vi.hoisted(() => ({
  state: {} as {
    conversations: ConversationSummary[];
    loaded: boolean;
    loadFailed: boolean;
  },
}));

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
    ...list.state,
    refresh: () => {},
    newChatNonce: 0,
    startNewChat: () => {},
    reportRoutedConversationId: () => {},
  }),
}));
vi.mock("@/lib/chatApi", () => ({
  deleteConversation: () => Promise.resolve(),
  listDocuments: () => Promise.resolve([]),
  uploadDocument: () => Promise.resolve(),
  deleteDocument: () => Promise.resolve(),
  downloadDocument: () => Promise.resolve(),
}));
vi.mock("@/components/chat/AboutYouProvider", () => ({
  useAboutYou: () => ({ open: () => {} }),
}));
vi.mock("@/components/chat/DocumentsPanel", () => ({
  DocumentsPanel: () => null,
}));

beforeEach(() => {
  stubMatchMedia();
});

describe("Sidebar loading", () => {
  it("hides the conversations skeleton from assistive tech", () => {
    list.state = { conversations: [], loaded: false, loadFailed: false };
    const { container } = render(<Sidebar />);

    const skeleton = container.querySelector('[data-skeleton="conversations"]');
    expect(skeleton).not.toBeNull();
    expect(skeleton).toHaveAttribute("aria-hidden", "true");
  });

  it.each<[string, ConversationSummary[], boolean, boolean, boolean]>([
    ["in flight", [], false, false, true],
    ["loaded", [conversation], true, false, false],
    ["failed", [], false, true, false],
  ])(
    "the nav is aria-busy only while the first list is in flight (%s)",
    (_, conversations, loaded, loadFailed, busy) => {
      list.state = { conversations, loaded, loadFailed };
      const { container } = render(<Sidebar />);

      const nav = container.querySelector("nav");
      expect(nav).not.toBeNull();
      if (busy) expect(nav).toHaveAttribute("aria-busy", "true");
      else expect(nav).not.toHaveAttribute("aria-busy", "true");
    },
  );
});
