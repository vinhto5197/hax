import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  INTERNAL_API_TIMEOUT_MS,
  InternalApiTimeout,
  internalFetch,
} from "@/lib/internalApi";

const fetchMock = vi.fn<typeof fetch>();

// A fetch that never answers on its own and rejects the way fetch does when
// its signal aborts.
function hangingFetch(_url: RequestInfo | URL, init?: RequestInit) {
  return new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () =>
      reject(new DOMException("The operation was aborted.", "AbortError")),
    );
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("internalFetch", () => {
  it("returns the API's response when it answers in time", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 401 }));
    const res = await internalFetch("http://api/x", { method: "POST" });
    expect(res.status).toBe(401);
    expect(fetchMock.mock.calls[0][0]).toBe("http://api/x");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST");
  });

  it("gives up after ten seconds with InternalApiTimeout", async () => {
    fetchMock.mockImplementation(hangingFetch);
    const pending = internalFetch("http://api/x", { method: "POST" });
    const outcome = pending.catch((e: unknown) => e);
    expect(INTERNAL_API_TIMEOUT_MS).toBe(10_000);
    await vi.advanceTimersByTimeAsync(INTERNAL_API_TIMEOUT_MS);
    const error = await outcome;
    expect(error).toBeInstanceOf(InternalApiTimeout);
  });

  it("is still waiting just before the limit", async () => {
    fetchMock.mockImplementation(hangingFetch);
    let settled = false;
    internalFetch("http://api/x", {}).then(
      () => (settled = true),
      () => (settled = true),
    );
    await vi.advanceTimersByTimeAsync(INTERNAL_API_TIMEOUT_MS - 1);
    expect(settled).toBe(false);
  });

  it("passes a network failure through unchanged, not as a timeout", async () => {
    const failure = new TypeError("fetch failed");
    fetchMock.mockRejectedValue(failure);
    await expect(internalFetch("http://api/x", {})).rejects.toBe(failure);
  });
});
