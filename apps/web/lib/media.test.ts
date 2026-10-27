import { act, renderHook } from "@testing-library/react";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DESKTOP, SHORT, useMediaQuery } from "@/lib/media";

type Listener = () => void;

type FakeQuery = {
  matches: boolean;
  listeners: Set<Listener>;
  addEventListener: ReturnType<typeof vi.fn>;
  removeEventListener: ReturnType<typeof vi.fn>;
};

let queries: Map<string, FakeQuery>;

function fake(query: string): FakeQuery {
  let entry = queries.get(query);
  if (!entry) {
    const listeners = new Set<Listener>();
    entry = {
      matches: false,
      listeners,
      addEventListener: vi.fn((type: string, l: Listener) => {
        if (type === "change") listeners.add(l);
      }),
      removeEventListener: vi.fn((type: string, l: Listener) => {
        if (type === "change") listeners.delete(l);
      }),
    };
    queries.set(query, entry);
  }
  return entry;
}

function fire(query: string, matches: boolean) {
  const entry = fake(query);
  entry.matches = matches;
  act(() => {
    for (const l of [...entry.listeners]) l();
  });
}

beforeEach(() => {
  queries = new Map();
  vi.stubGlobal("matchMedia", (query: string) => {
    const entry = fake(query);
    return {
      get matches() {
        return entry.matches;
      },
      media: query,
      onchange: null,
      addEventListener: entry.addEventListener,
      removeEventListener: entry.removeEventListener,
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    };
  });
});

describe("useMediaQuery", () => {
  it.each([true, false])("returns the current match (%s)", (matches) => {
    fake(DESKTOP).matches = matches;
    const { result } = renderHook(() => useMediaQuery(DESKTOP, !matches));
    expect(result.current).toBe(matches);
  });

  it("re-renders with the new value when the query changes", () => {
    fake(SHORT).matches = false;
    const { result } = renderHook(() => useMediaQuery(SHORT, false));
    expect(result.current).toBe(false);
    fire(SHORT, true);
    expect(result.current).toBe(true);
    fire(SHORT, false);
    expect(result.current).toBe(false);
  });

  it("subscribes once per mount, not per render, and unsubscribes on unmount", () => {
    const entry = fake(DESKTOP);
    const { rerender, unmount } = renderHook(() =>
      useMediaQuery(DESKTOP, false),
    );
    expect(entry.addEventListener).toHaveBeenCalledTimes(1);
    expect(entry.addEventListener).toHaveBeenCalledWith(
      "change",
      expect.any(Function),
    );
    expect(entry.listeners.size).toBe(1);

    rerender();
    rerender();
    expect(entry.addEventListener).toHaveBeenCalledTimes(1);
    expect(entry.removeEventListener).not.toHaveBeenCalled();

    unmount();
    expect(entry.removeEventListener).toHaveBeenCalledTimes(1);
    expect(entry.listeners.size).toBe(0);
  });

  it.each([true, false])(
    "renders serverValue (%s) on the server, whatever the browser says",
    (serverValue) => {
      fake(DESKTOP).matches = !serverValue;
      function Probe() {
        return createElement(
          "span",
          null,
          String(useMediaQuery(DESKTOP, serverValue)),
        );
      }
      expect(renderToString(createElement(Probe))).toContain(
        `>${String(serverValue)}<`,
      );
    },
  );
});
