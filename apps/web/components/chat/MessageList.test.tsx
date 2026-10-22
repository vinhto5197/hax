import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { MessageList } from "@/components/chat/MessageList";

beforeEach(() => {
  // jsdom has no layout; auto-scroll calls must not throw.
  Element.prototype.scrollIntoView = () => {};
  Element.prototype.scrollTo = () => {};
});

function renderList(isLoading: boolean, status: string | null) {
  render(
    <MessageList
      messages={[]}
      isLoading={isLoading}
      streamingContent=""
      status={status}
    />,
  );
}

describe("MessageList status line", () => {
  it("is a polite live region reading 'Assistant is thinking...'", () => {
    renderList(true, null);
    const line = screen.getByRole("status");
    expect(line).toHaveTextContent("Assistant is thinking...");
    expect(line).toHaveAttribute("aria-live", "polite");
  });

  it("announces the tool status text", () => {
    renderList(true, "Searching documents…");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Searching documents…",
    );
  });

  it("is absent when not loading", () => {
    renderList(false, null);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
