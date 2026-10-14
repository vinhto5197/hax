import { signOut } from "next-auth/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DemoLimitError,
  deleteConversation,
  deleteDocument,
  listConversations,
  streamChat,
  uploadDocument,
} from "@/lib/chatApi";
import { sseEvent, sseResponse } from "@/lib/testing/sse";

vi.mock("next-auth/react", () => ({
  signOut: vi.fn(() => Promise.resolve()),
}));

const source = {
  document_id: "d1",
  filename: "notes.md",
  chunk_idx: 0,
  excerpt: "the passage",
  distance: 0.2,
};

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(response));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function recorder() {
  const calls: Array<[string, unknown]> = [];
  return {
    calls,
    handlers: {
      onConversationId: (id: string) => calls.push(["conversation", id]),
      onChunk: (c: string) => calls.push(["chunk", c]),
      onStatus: (s: string) => calls.push(["status", s]),
      onSources: (s: unknown) => calls.push(["sources", s]),
    },
  };
}

describe("streamChat", () => {
  it("posts the prompt, conversation and model as JSON with credentials", async () => {
    const fetchMock = stubFetch(sseResponse([sseEvent("[DONE]")]));

    await streamChat("hi", "c1", recorder().handlers, "some-model");

    expect(fetchMock).toHaveBeenCalledWith("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: "hi",
        conversation_id: "c1",
        model: "some-model",
      }),
      credentials: "include",
    });
  });

  it("hands each event to its handler in order and stops at [DONE]", async () => {
    stubFetch(
      sseResponse([
        sseEvent({ conversation_id: "c1" }) +
          sseEvent({ status: "Searching your documents" }) +
          sseEvent({ content: "Hello" }) +
          sseEvent({ content: " world" }) +
          sseEvent({ sources: [source] }) +
          sseEvent("[DONE]") +
          sseEvent({ content: "after done" }),
      ]),
    );
    const { calls, handlers } = recorder();

    await streamChat("hi", null, handlers);

    expect(calls).toEqual([
      ["conversation", "c1"],
      ["status", "Searching your documents"],
      ["chunk", "Hello"],
      ["chunk", " world"],
      ["sources", [source]],
    ]);
  });

  it("reassembles an event the network split across reads", async () => {
    const event = sseEvent({ content: "split here" });
    stubFetch(
      sseResponse([event.slice(0, 9), event.slice(9, 20), event.slice(20)]),
    );
    const { calls, handlers } = recorder();

    await streamChat("hi", null, handlers);

    expect(calls).toEqual([["chunk", "split here"]]);
  });

  it("reassembles a multi-byte character split between two reads", async () => {
    const bytes = new TextEncoder().encode(sseEvent({ content: "café" }));
    const cut = bytes.indexOf(0xc3) + 1; // inside the two bytes of "é"
    stubFetch(sseResponse([bytes.slice(0, cut), bytes.slice(cut)]));
    const { calls, handlers } = recorder();

    await streamChat("hi", null, handlers);

    expect(calls).toEqual([["chunk", "café"]]);
  });

  it("skips malformed, empty and unknown events and keeps reading", async () => {
    stubFetch(
      sseResponse([
        "data: {not json\n\n" +
          sseEvent({ content: "" }) +
          sseEvent({ status: "" }) +
          sseEvent({ something: "else" }) +
          ": a comment line\n\n" +
          sseEvent({ content: 42 }) +
          sseEvent({ content: "kept" }) +
          sseEvent("[DONE]"),
      ]),
    );
    const { calls, handlers } = recorder();

    await streamChat("hi", null, handlers);

    expect(calls).toEqual([["chunk", "kept"]]);
  });

  it("drops a whole sources event when one element is malformed", async () => {
    stubFetch(
      sseResponse([
        sseEvent({ sources: [source, { ...source, distance: "near" }] }) +
          sseEvent("[DONE]"),
      ]),
    );
    const { calls, handlers } = recorder();

    await streamChat("hi", null, handlers);

    expect(calls).toEqual([]);
  });

  it("salvages a trailing chunk when the stream ends without a blank line", async () => {
    stubFetch(
      sseResponse([sseEvent({ content: "a" }), 'data: {"content":"b"}']),
    );
    const { calls, handlers } = recorder();

    await streamChat("hi", null, handlers);

    expect(calls).toEqual([
      ["chunk", "a"],
      ["chunk", "b"],
    ]);
  });

  it("works without the optional status and sources handlers", async () => {
    stubFetch(
      sseResponse([
        sseEvent({ status: "Searching" }) +
          sseEvent({ sources: [source] }) +
          sseEvent({ content: "ok" }) +
          sseEvent("[DONE]"),
      ]),
    );
    const chunks: string[] = [];

    await streamChat("hi", null, {
      onConversationId: () => {},
      onChunk: (c) => chunks.push(c),
    });

    expect(chunks).toEqual(["ok"]);
  });

  it("throws DemoLimitError on the demo-limit 403", async () => {
    stubFetch(json({ detail: { code: "demo_limit" } }, 403));

    await expect(
      streamChat("hi", null, recorder().handlers),
    ).rejects.toBeInstanceOf(DemoLimitError);
  });

  it.each([
    ["another 403", json({ detail: "Forbidden" }, 403), "API 403"],
    ["a 500", new Response("boom", { status: 500 }), "API 500"],
  ])("throws a plain error on %s", async (_label, response, message) => {
    stubFetch(response);

    const call = streamChat("hi", null, recorder().handlers);

    await expect(call).rejects.toThrow(message);
    await expect(call).rejects.not.toBeInstanceOf(DemoLimitError);
  });
});

describe("error mapping on the JSON helpers", () => {
  it("surfaces FastAPI's string detail on a failed upload", async () => {
    stubFetch(json({ detail: "File too large" }, 413));

    await expect(uploadDocument(new File(["x"], "a.txt"))).rejects.toThrow(
      "File too large",
    );
  });

  it("falls back to the status for a validation-array detail", async () => {
    stubFetch(json({ detail: [{ msg: "field required" }] }, 422));

    await expect(uploadDocument(new File(["x"], "a.txt"))).rejects.toThrow(
      "API 422",
    );
  });

  it("falls back to the status for a non-JSON error body", async () => {
    stubFetch(new Response("<html>bad gateway</html>", { status: 502 }));

    await expect(deleteDocument("d1")).rejects.toThrow("API 502");
  });

  it("sends the upload as the multipart field the API names `file`", async () => {
    const fetchMock = stubFetch(json({ id: "d1" }, 201));
    const file = new File(["x"], "a.txt");

    await uploadDocument(file);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it.each([
    ["deleteDocument", () => deleteDocument("d1")],
    ["deleteConversation", () => deleteConversation("c1")],
  ])("%s treats a 404 as already deleted", async (_name, call) => {
    stubFetch(new Response(null, { status: 404 }));

    await expect(call()).resolves.toBeUndefined();
  });

  it("listConversations throws with the status on failure", async () => {
    stubFetch(new Response(null, { status: 500 }));

    await expect(listConversations()).rejects.toThrow("API 500");
  });
});

describe("a 401 evicts the session", () => {
  // The eviction latch is module state that never resets on its own, so each
  // test here loads a fresh copy of the module.
  async function freshModule() {
    vi.resetModules();
    return import("@/lib/chatApi");
  }

  beforeEach(() => {
    vi.mocked(signOut).mockClear();
  });

  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("signs out once for parallel 401s, back to /login from the app", async () => {
    window.history.replaceState(null, "", "/chat/c1");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(null, { status: 401 }))),
    );
    const api = await freshModule();

    await Promise.allSettled([api.listConversations(), api.listDocuments()]);

    expect(signOut).toHaveBeenCalledTimes(1);
    expect(signOut).toHaveBeenCalledWith({ callbackUrl: "/login" });
  });

  it("re-arms after a failed sign-out, so a later 401 retries", async () => {
    vi.mocked(signOut).mockRejectedValueOnce(new Error("network"));
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(null, { status: 401 }))),
    );
    const api = await freshModule();

    await api.listConversations().catch(() => {});
    await new Promise((resolve) => setTimeout(resolve, 0));
    await api.listConversations().catch(() => {});

    expect(signOut).toHaveBeenCalledTimes(2);
  });

  it("signs out in place on the landing page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(null, { status: 401 }))),
    );
    const api = await freshModule();

    await api.listConversations().catch(() => {});

    expect(signOut).toHaveBeenCalledWith({ callbackUrl: "/" });
  });
});
