import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MessageList } from "@/components/chat/MessageList";
import type { ChatMessage } from "@/lib/chatApi";
import { REDUCED_MOTION } from "@/lib/media";
import { stubMatchMedia } from "@/test-utils/matchMedia";

beforeEach(() => {
  // jsdom has no Element.scrollTo; the jump button calls it.
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

type FakeObserver = {
  callback: ResizeObserverCallback;
  observed: Element[];
  disconnected: boolean;
};

function stubResizeObserver(): FakeObserver[] {
  const instances: FakeObserver[] = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      record: FakeObserver;
      constructor(callback: ResizeObserverCallback) {
        this.record = { callback, observed: [], disconnected: false };
        instances.push(this.record);
      }
      observe(el: Element) {
        this.record.observed.push(el);
      }
      unobserve() {}
      disconnect() {
        this.record.disconnected = true;
      }
    },
  );
  return instances;
}

// jsdom has no layout, so the scroller's geometry is supplied by hand.
function setGeometry(
  el: HTMLElement,
  scrollHeight: number,
  clientHeight: number,
) {
  Object.defineProperty(el, "scrollHeight", {
    configurable: true,
    get: () => scrollHeight,
  });
  Object.defineProperty(el, "clientHeight", {
    configurable: true,
    get: () => clientHeight,
  });
}

function renderScroller() {
  const result = render(
    <MessageList
      messages={[]}
      isLoading={false}
      streamingContent=""
      status={null}
    />,
  );
  const el = result.container.firstElementChild as HTMLElement;
  return { ...result, el };
}

function fireResize(observer: FakeObserver) {
  act(() => {
    observer.callback([], {} as ResizeObserver);
  });
}

describe("MessageList stick-to-bottom on scroller resize", () => {
  it("re-pins to the bottom on a size change while stuck", () => {
    const observers = stubResizeObserver();
    const { el } = renderScroller();
    expect(observers).toHaveLength(1);
    expect(observers[0].observed).toContain(el);

    setGeometry(el, 1000, 400);
    el.scrollTop = 600;
    fireEvent.scroll(el);

    // A resize clamps scrollTop without a scroll the list would act on.
    setGeometry(el, 1200, 400);
    el.scrollTop = 500;
    fireResize(observers[0]);

    expect(el.scrollTop).toBe(1200);
  });

  it("leaves the position alone after the user scrolled up", () => {
    const observers = stubResizeObserver();
    const { el } = renderScroller();

    setGeometry(el, 1000, 400);
    el.scrollTop = 600;
    fireEvent.scroll(el);
    el.scrollTop = 100;
    fireEvent.scroll(el);

    setGeometry(el, 1200, 400);
    fireResize(observers[0]);

    expect(el.scrollTop).toBe(100);
  });

  it("disconnects the observer on unmount", () => {
    const observers = stubResizeObserver();
    const { unmount } = renderScroller();
    expect(observers[0].disconnected).toBe(false);

    unmount();

    expect(observers[0].disconnected).toBe(true);
  });
});

const JUMP = { name: "Jump to latest" };

// Only the reduced-motion query is ever asked here.
function stubReducedMotion(reduce: boolean) {
  stubMatchMedia((query) => reduce && query === REDUCED_MOTION);
}

const BASE_MESSAGES: ChatMessage[] = [
  { role: "user", content: "First question" },
  { role: "assistant", content: "First answer" },
];

function listProps(overrides: Partial<ComponentProps<typeof MessageList>>) {
  return {
    messages: BASE_MESSAGES,
    isLoading: false,
    streamingContent: "",
    status: null,
    ...overrides,
  };
}

function renderThread() {
  const result = render(<MessageList {...listProps({})} />);
  const el = result.container.firstElementChild as HTMLElement;
  return { ...result, el };
}

// At the bottom of a 1000 px thread in a 400 px view, then 500 px up: an
// upward scroll that leaves the bottom by more than 64 px.
function scrollUpAndRelease(el: HTMLElement) {
  setGeometry(el, 1000, 400);
  el.scrollTop = 600;
  fireEvent.scroll(el);
  el.scrollTop = 100;
  fireEvent.scroll(el);
}

describe("MessageList Jump to latest", () => {
  beforeEach(() => {
    stubResizeObserver();
    stubReducedMotion(false);
  });

  it("The button is absent at first, present after an upward scroll past 64 px, absent after scrolling back within 64 px", () => {
    const { el } = renderThread();
    expect(screen.queryByRole("button", JUMP)).toBeNull();

    scrollUpAndRelease(el);
    expect(screen.queryByRole("button", JUMP)).not.toBeNull();

    el.scrollTop = 560;
    fireEvent.scroll(el);
    expect(screen.queryByRole("button", JUMP)).toBeNull();
  });

  it("Jump to latest scrolls smoothly when reduced motion is not asked for", () => {
    const { el } = renderThread();
    const scrollTo = vi.fn();
    el.scrollTo = scrollTo as unknown as HTMLElement["scrollTo"];
    scrollUpAndRelease(el);

    fireEvent.click(screen.getByRole("button", JUMP));

    expect(scrollTo).toHaveBeenCalledTimes(1);
    expect(scrollTo).toHaveBeenCalledWith({ top: 1000, behavior: "smooth" });
    expect(screen.queryByRole("button", JUMP)).toBeNull();
  });

  it("Jump to latest scrolls instantly when reduced motion is asked for", () => {
    stubReducedMotion(true);
    const { el } = renderThread();
    const scrollTo = vi.fn();
    el.scrollTo = scrollTo as unknown as HTMLElement["scrollTo"];
    scrollUpAndRelease(el);

    fireEvent.click(screen.getByRole("button", JUMP));

    expect(scrollTo).toHaveBeenCalledTimes(1);
    expect(scrollTo).toHaveBeenCalledWith({ top: 1000, behavior: "auto" });
  });

  it("After Jump to latest the next content change pins the view to the bottom", () => {
    const { el, rerender } = renderThread();
    scrollUpAndRelease(el);

    // The stubbed scrollTo moves nothing: only the re-engaged follow can.
    fireEvent.click(screen.getByRole("button", JUMP));
    expect(el.scrollTop).toBe(100);

    setGeometry(el, 1400, 400);
    rerender(
      <MessageList
        {...listProps({ isLoading: true, streamingContent: "A new piece" })}
      />,
    );

    expect(el.scrollTop).toBe(1400);
    expect(screen.queryByRole("button", JUMP)).toBeNull();
  });

  it("A new user turn re-engages the follow after the user scrolled up", () => {
    const { el, rerender } = renderThread();
    scrollUpAndRelease(el);

    // An assistant message is not a send: the view stays where the user is.
    const withReply: ChatMessage[] = [
      ...BASE_MESSAGES,
      { role: "assistant", content: "Another answer" },
    ];
    setGeometry(el, 1200, 400);
    rerender(<MessageList {...listProps({ messages: withReply })} />);
    expect(el.scrollTop).toBe(100);
    expect(screen.queryByRole("button", JUMP)).not.toBeNull();

    const withQuestion: ChatMessage[] = [
      ...withReply,
      { role: "user", content: "A new question" },
    ];
    setGeometry(el, 1400, 400);
    rerender(<MessageList {...listProps({ messages: withQuestion })} />);
    expect(el.scrollTop).toBe(1400);
    expect(screen.queryByRole("button", JUMP)).toBeNull();
  });
});
