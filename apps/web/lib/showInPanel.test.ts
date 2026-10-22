import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from "vitest";

import { revealDocumentRow } from "@/lib/showInPanel";

// jsdom does not implement scrollIntoView; the stub lives on the prototype and
// is put back after each test so no other suite sees it.
const originalScrollIntoView = Element.prototype.scrollIntoView;
let scrollIntoView: Mock<Element["scrollIntoView"]>;

beforeEach(() => {
  scrollIntoView = vi.fn<Element["scrollIntoView"]>();
  Element.prototype.scrollIntoView = scrollIntoView;
});

afterEach(() => {
  Element.prototype.scrollIntoView = originalScrollIntoView;
  document.body.innerHTML = "";
  vi.useRealTimers();
});

function mountRow(inDetails = false): HTMLElement {
  document.body.innerHTML = inDetails
    ? `<details><summary>Documents</summary><div id="doc-abc"></div></details>`
    : `<div id="doc-abc"></div>`;
  return document.getElementById("doc-abc")!;
}

describe("revealDocumentRow", () => {
  it("returns false when no row has the document's id", () => {
    expect(revealDocumentRow("missing")).toBe(false);
    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("scrolls to the nearest edge and leaves the behaviour to CSS (reduced motion)", () => {
    mountRow();
    expect(revealDocumentRow("abc")).toBe(true);
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    const options = scrollIntoView.mock.calls[0][0] as ScrollIntoViewOptions;
    expect(options.block).toBe("nearest");
    // An explicit "smooth" (or "instant") overrides the reduced-motion CSS.
    expect([undefined, "auto"]).toContain(options.behavior);
  });

  it("opens the enclosing <details>", () => {
    mountRow(true);
    const details = document.querySelector("details")!;
    expect(details.open).toBe(false);
    revealDocumentRow("abc");
    expect(details.hasAttribute("open")).toBe(true);
  });

  it("flashes the row and clears the flash after 1200 ms", () => {
    vi.useFakeTimers();
    const row = mountRow();
    revealDocumentRow("abc");
    expect(row.getAttribute("data-flash")).toBe("true");
    vi.advanceTimersByTime(1199);
    expect(row.getAttribute("data-flash")).toBe("true");
    vi.advanceTimersByTime(1);
    expect(row.hasAttribute("data-flash")).toBe(false);
  });
});
