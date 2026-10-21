import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Shell } from "@/components/chat/Shell";

// Plain functions, not vi.fn: the config's mockReset would clear a queued
// return value before each test.
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
vi.mock("@/components/chat/ConversationsProvider", () => ({
  useConversations: () => ({ startNewChat: () => {} }),
}));
vi.mock("@/components/chat/Sidebar", () => ({ Sidebar: () => null }));

beforeEach(() => {
  // Every query false: the phone shell, where the drawer exists.
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

function openDrawer() {
  render(
    <Shell>
      <p>content</p>
    </Shell>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
  return screen.getByRole("button", { name: "Close menu" });
}

describe("Shell phone drawer scrim", () => {
  it("is kept out of the Tab order", () => {
    expect(openDrawer()).toHaveAttribute("tabindex", "-1");
  });

  it("closes the drawer on a click", () => {
    const scrim = openDrawer();
    expect(screen.getByRole("dialog", { name: "Menu" })).toBeInTheDocument();
    fireEvent.click(scrim);
    expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Close menu" })).toBeNull();
  });
});
