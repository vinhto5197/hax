import { vi } from "vitest";

// Test-only. jsdom has no matchMedia; this one answers each query once and
// never fires a change.
export function stubMatchMedia(
  matches: (query: string) => boolean = () => false,
): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: matches(query),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}
