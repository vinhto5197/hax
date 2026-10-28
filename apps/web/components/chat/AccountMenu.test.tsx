import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountMenu } from "@/components/chat/AccountMenu";

const { aboutYou, signOut } = vi.hoisted(() => ({
  aboutYou: { current: null as null | { open: () => void } },
  signOut: vi.fn(),
}));
vi.mock("next-auth/react", () => ({ signOut }));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: { href: string; children: ReactNode } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push: () => {}, replace: () => {}, prefetch: () => {} }),
}));
vi.mock("@/components/chat/AboutYouProvider", () => ({
  useAboutYou: () => aboutYou.current,
}));

const NAME = "Ada Lovelace";
const EMAIL = "ada@example.com";
const ITEMS = ["About you", "Privacy", "Sign out"];

beforeEach(() => {
  aboutYou.current = { open: vi.fn() };
});

function renderMenu() {
  return render(
    <div>
      <p>outside the menu</p>
      <AccountMenu name={NAME} email={EMAIL} onNavigate={() => {}} />
    </div>,
  );
}

function accountButton() {
  return screen.getByRole("button", { name: "Account menu" });
}

function item(text: string) {
  return screen.queryByText(text, { exact: true });
}

function open() {
  fireEvent.click(accountButton());
}

describe("AccountMenu", () => {
  it("is a button named Account menu showing the name and email, closed at first", () => {
    renderMenu();
    const button = accountButton();
    expect(within(button).getByText(NAME)).toBeInTheDocument();
    expect(within(button).getByText(EMAIL)).toBeInTheDocument();
    for (const text of ITEMS) expect(item(text)).toBeNull();
  });

  it("opens on click with About you, Privacy and Sign out, in that order", () => {
    renderMenu();
    open();
    const found = ITEMS.map((text) => item(text));
    for (const el of found) expect(el).toBeInTheDocument();
    for (let i = 1; i < found.length; i++) {
      const order = found[i - 1]!.compareDocumentPosition(found[i]!);
      expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it("closes on a click outside", () => {
    renderMenu();
    open();
    const outside = screen.getByText("outside the menu");
    fireEvent.pointerDown(outside);
    fireEvent.mouseDown(outside);
    fireEvent.click(outside);
    for (const text of ITEMS) expect(item(text)).toBeNull();
  });

  it("Escape closes the menu and is marked defaultPrevented", () => {
    renderMenu();
    open();
    // fireEvent returns false when a handler called preventDefault().
    const notPrevented = fireEvent.keyDown(item("About you")!, {
      key: "Escape",
      code: "Escape",
    });
    expect(notPrevented).toBe(false);
    for (const text of ITEMS) expect(item(text)).toBeNull();
  });

  it("About you opens the dialog through the provider", () => {
    renderMenu();
    open();
    fireEvent.click(item("About you")!);
    expect(aboutYou.current!.open).toHaveBeenCalledTimes(1);
  });

  it("leaves out About you when there is no provider", () => {
    aboutYou.current = null;
    renderMenu();
    open();
    expect(item("About you")).toBeNull();
    expect(item("Privacy")).toBeInTheDocument();
    expect(item("Sign out")).toBeInTheDocument();
  });

  it("Privacy links to /privacy", () => {
    renderMenu();
    open();
    expect(item("Privacy")!.closest("a")).toHaveAttribute("href", "/privacy");
  });

  it("Sign out signs the member out", () => {
    renderMenu();
    open();
    fireEvent.click(item("Sign out")!);
    expect(signOut).toHaveBeenCalledTimes(1);
  });
});
