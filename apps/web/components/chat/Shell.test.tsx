import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
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

// Children standing in for the page and for the About you dialog, which the
// provider renders outside the drawer.
function openDrawerOver(children: ReactNode) {
  render(<Shell>{children}</Shell>);
  fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
  return screen.getByRole("button", { name: "Close menu" });
}

describe("Shell drawer focus return", () => {
  it("leaves focus where it is when the drawer closes while focus is inside an open modal dialog", () => {
    const scrim = openDrawerOver(
      createPortal(
        <div role="dialog" aria-modal="true" aria-label="About you">
          <textarea aria-label="About you" />
        </div>,
        document.body,
      ),
    );
    const field = screen.getByRole("textbox", { name: "About you" });
    field.focus();
    expect(field).toHaveFocus();

    fireEvent.click(scrim);

    expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull();
    expect(field).toHaveFocus();
  });

  it("returns focus to the menu button when the drawer closes otherwise", () => {
    const scrim = openDrawerOver(<button type="button">page button</button>);
    screen.getByRole("button", { name: "page button" }).focus();

    fireEvent.click(scrim);

    expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveFocus();
  });

  it("returns focus to the menu button when focus is inside a dialog that is not modal", () => {
    const scrim = openDrawerOver(
      <div role="dialog" aria-label="Not modal">
        <textarea aria-label="Loose field" />
      </div>,
    );
    screen.getByRole("textbox", { name: "Loose field" }).focus();

    fireEvent.click(scrim);

    expect(screen.getByRole("button", { name: "Open menu" })).toHaveFocus();
  });
});

describe("Shell drawer Escape", () => {
  it("keeps the drawer open on an Escape whose defaultPrevented is true", () => {
    openDrawerOver(
      <input
        aria-label="handles its own Escape"
        onKeyDown={(event) => {
          if (event.key === "Escape") event.preventDefault();
        }}
      />,
    );
    fireEvent.keyDown(
      screen.getByRole("textbox", { name: "handles its own Escape" }),
      { key: "Escape", code: "Escape" },
    );
    expect(screen.getByRole("dialog", { name: "Menu" })).toBeInTheDocument();
  });

  it("closes the drawer on a plain Escape", () => {
    openDrawerOver(<input aria-label="plain field" />);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "plain field" }), {
      key: "Escape",
      code: "Escape",
    });
    expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull();
  });
});
