import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
