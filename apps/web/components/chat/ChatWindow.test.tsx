import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatWindow } from "@/components/chat/ChatWindow";
import { stubMatchMedia } from "@/test-utils/matchMedia";

// Plain functions reading a mutable value, not vi.fn: the config's mockReset
// would clear a queued return value before each test.
let chatError: string | null = null;
let restoreDraft: string | null = null;
let stoppedNotice = false;
let canRetry = false;

// jsdom has no matchMedia; the composer reads it before focusing.
beforeEach(() => stubMatchMedia());

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
    stillAnswering: false,
    restoreDraft,
    send: async () => {},
    stop: async () => {},
    canStop: false,
    stoppedNotice,
    retry: async () => {},
    canRetry,
  }),
}));

beforeEach(() => {
  chatError = null;
  restoreDraft = null;
  stoppedNotice = false;
  canRetry = false;
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

describe("ChatWindow composer", () => {
  it("puts the hook's restored draft back into the composer", () => {
    restoreDraft = "my unsent question";
    render(<ChatWindow conversationId="c1" demo={false} />);
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(
      "my unsent question",
    );
  });
});

describe("ChatWindow stopped notice", () => {
  it("is announced as a polite status with a Try again button", () => {
    stoppedNotice = true;
    canRetry = true;
    render(<ChatWindow conversationId="c1" demo={false} />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("You stopped this reply.");
    expect(
      within(status).getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });

  it("is not an alert", () => {
    stoppedNotice = true;
    canRetry = true;
    render(<ChatWindow conversationId="c1" demo={false} />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("is absent without a stop", () => {
    render(<ChatWindow conversationId="c1" demo={false} />);
    expect(screen.queryByText("You stopped this reply.")).toBeNull();
  });
});
