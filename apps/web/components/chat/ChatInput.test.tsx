import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInput, PROMPT_MAX_LENGTH } from "@/components/chat/ChatInput";

describe("ChatInput composer", () => {
  it("names the textarea 'Message' and keeps its placeholder", () => {
    render(<ChatInput onSend={async () => {}} disabled={false} />);
    const textbox = screen.getByRole("textbox", { name: "Message" });
    expect(textbox).toHaveAttribute("placeholder", "Type your prompt...");
  });

  it("caps the textarea at the API's 20000-character prompt limit", () => {
    render(<ChatInput onSend={async () => {}} disabled={false} />);
    const textbox = screen.getByRole("textbox", { name: "Message" });
    // The literal is ChatRequest.prompt's max_length; it is asserted apart
    // from the constant so a drift on either side fails here.
    expect(PROMPT_MAX_LENGTH).toBe(20000);
    expect(textbox).toHaveAttribute("maxlength", "20000");
  });
});

describe("ChatInput auto-grow on resize", () => {
  // jsdom has no layout: scrollHeight is always 0 and the max-h-[40vh] class
  // is never applied, so both inputs to the measure are faked here.
  let scrollHeight = 0;

  beforeEach(() => {
    scrollHeight = 120;
    Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", {
      configurable: true,
      get: () => scrollHeight,
    });
    const realGetComputedStyle = window.getComputedStyle.bind(window);
    // Only the textarea's maxHeight is faked; Testing Library's role and name
    // queries still need a real declaration (getPropertyValue, display, ...).
    vi.spyOn(window, "getComputedStyle").mockImplementation((el, pseudo) => {
      const style = realGetComputedStyle(el, pseudo);
      if (!(el instanceof HTMLTextAreaElement)) return style;
      return new Proxy(style, {
        get(target, prop) {
          if (prop === "maxHeight") return "200px";
          const value = Reflect.get(target, prop);
          return typeof value === "function" ? value.bind(target) : value;
        },
      });
    });
  });

  afterEach(() => {
    // The own property shadows Element.prototype's real getter; deleting it
    // restores jsdom's behaviour for later suites.
    Reflect.deleteProperty(HTMLTextAreaElement.prototype, "scrollHeight");
  });

  it("re-measures the textarea when the window resizes", () => {
    render(<ChatInput onSend={async () => {}} disabled={false} />);
    const textbox = screen.getByRole("textbox", { name: "Message" });
    expect(textbox.style.height).toBe("120px");
    expect(textbox.style.overflowY).toBe("hidden");

    scrollHeight = 300;
    expect(textbox.style.height).toBe("120px");

    act(() => {
      window.dispatchEvent(new Event("resize"));
    });

    expect(textbox.style.height).toBe("200px");
    expect(textbox.style.overflowY).toBe("auto");
  });

  it("stops measuring on resize after unmount", () => {
    const { unmount } = render(
      <ChatInput onSend={async () => {}} disabled={false} />,
    );
    const textbox = screen.getByRole("textbox", { name: "Message" });
    textbox.style.height = "7px";

    unmount();
    scrollHeight = 300;
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });

    expect(textbox.style.height).toBe("7px");
  });
});
