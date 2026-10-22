import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatWindow } from "@/components/chat/ChatWindow";

// Plain functions reading a mutable value, not vi.fn: the config's mockReset
// would clear a queued return value before each test.
let chatError: string | null = null;

vi.mock("@/components/chat/ConversationsProvider", () => ({
  useConversations: () => ({
    conversations: [],
    refresh: () => {},
    newChatNonce: 0,
    startNewChat: () => {},
    reportRoutedConversationId: () => {},
  }),
}));
vi.mock("@/hooks/useChat", () => ({
  useChat: () => ({
    messages: [],
    isLoading: false,
    streamingContent: "",
    status: null,
    error: chatError,
    limited: false,
    send: async () => {},
  }),
}));

beforeEach(() => {
  chatError = null;
  // jsdom has no layout; auto-scroll calls must not throw.
  Element.prototype.scrollIntoView = () => {};
  Element.prototype.scrollTo = () => {};
});

describe("ChatWindow error", () => {
  it("is announced as an alert", () => {
    chatError = "Something went wrong";
    render(<ChatWindow conversationId="c1" demo={false} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
  });

  it("renders no alert without an error", () => {
    render(<ChatWindow conversationId="c1" demo={false} />);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
