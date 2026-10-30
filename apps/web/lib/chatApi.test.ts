import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Source, StreamHandlers } from "@/lib/chatApi";
import { sseEvent, sseResponse } from "@/test-utils/sse";

const { signOut } = vi.hoisted(() => ({ signOut: vi.fn() }));
vi.mock("next-auth/react", () => ({ signOut }));

type ChatApi = typeof import("@/lib/chatApi");

// The sign-out latch is module state; every test loads a fresh module so one
// test's 401 cannot suppress another's sign-out.
async function load(): Promise<ChatApi> {
  vi.resetModules();
  return import("@/lib/chatApi");
}

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function respondWith(make: () => Response): void {
  fetchMock.mockImplementation(async () => make());
}

function call(index = 0): { url: string; init: RequestInit } {
  const [input, init] = fetchMock.mock.calls[index];
  return { url: String(input), init: init ?? {} };
}

function handlers(): StreamHandlers & {
  log: Array<[string, unknown]>;
  onStatus: ReturnType<typeof vi.fn>;
  onSources: ReturnType<typeof vi.fn>;
} {
  const log: Array<[string, unknown]> = [];
  return {
    log,
    onConversationId: vi.fn((id: string) => log.push(["conversation", id])),
    onChunk: vi.fn((content: string) => log.push(["chunk", content])),
    onStatus: vi.fn((status: string) => log.push(["status", status])),
    onSources: vi.fn((sources: Source[]) => log.push(["sources", sources])),
  };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const source: Source = {
  document_id: "d1",
  filename: "notes.md",
  chunk_idx: 2,
  excerpt: "the passage",
  distance: 0.12,
};

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  signOut.mockResolvedValue(undefined);
});

afterEach(() => {
  window.history.pushState({}, "", "/");
});

const everyCall: Array<
  [string, string, string, (api: ChatApi) => Promise<unknown>]
> = [
  [
    "listConversations",
    "GET",
    "/api/conversations",
    (api) => api.listConversations(),
  ],
  [
    "getConversation",
    "GET",
    "/api/conversations/c1",
    (api) => api.getConversation("c1"),
  ],
  ["listDocuments", "GET", "/api/documents", (api) => api.listDocuments()],
  [
    "uploadDocument",
    "POST",
    "/api/documents",
    (api) =>
      api.uploadDocument(new File(["x"], "a.txt", { type: "text/plain" })),
  ],
  [
    "deleteDocument",
    "DELETE",
    "/api/documents/d1",
    (api) => api.deleteDocument("d1"),
  ],
  [
    "downloadDocument",
    "GET",
    "/api/documents/d1/download",
    (api) => api.downloadDocument("d1", "a.txt"),
  ],
  [
    "deleteConversation",
    "DELETE",
    "/api/conversations/c1",
    (api) => api.deleteConversation("c1"),
  ],
  [
    "streamChat",
    "POST",
    "/api/chat",
    (api) =>
      api.streamChat("hi", null, {
        onConversationId: vi.fn(),
        onChunk: vi.fn(),
      }),
  ],
];

describe("transport", () => {
  it.each(everyCall)(
    "%s sends %s %s with credentials included",
    async (_name, method, url, invoke) => {
      const api = await load();
      respondWith(() => new Response(null, { status: 500 }));
      await invoke(api).catch(() => {});
      expect(fetchMock).toHaveBeenCalledTimes(1);
      const sent = call();
      expect(sent.url).toBe(url);
      expect((sent.init.method ?? "GET").toUpperCase()).toBe(method);
      expect(sent.init.credentials).toBe("include");
    },
  );
});

describe("session eviction", () => {
  it.each(everyCall)(
    "a 401 from %s signs out to /login and still rejects",
    async (_name, _method, _url, invoke) => {
      window.history.pushState({}, "", "/chat/c1");
      const api = await load();
      respondWith(() => jsonResponse({ detail: "Not authenticated" }, 401));
      await expect(invoke(api)).rejects.toThrow();
      expect(signOut).toHaveBeenCalledTimes(1);
      expect(signOut).toHaveBeenCalledWith({ callbackUrl: "/login" });
    },
  );

  it("a 401 on the landing page signs out back to /", async () => {
    window.history.pushState({}, "", "/");
    const api = await load();
    respondWith(() => jsonResponse({ detail: "Not authenticated" }, 401));
    await expect(api.listConversations()).rejects.toThrow();
    expect(signOut).toHaveBeenCalledWith({ callbackUrl: "/" });
  });

  it("parallel 401s sign out exactly once", async () => {
    const api = await load();
    respondWith(() => new Response(null, { status: 401 }));
    const results = await Promise.allSettled([
      api.listConversations(),
      api.listDocuments(),
      api.getConversation("c1"),
      api.deleteDocument("d1"),
    ]);
    expect(results.every((r) => r.status === "rejected")).toBe(true);
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("a rejected sign-out lets the next 401 try again", async () => {
    const api = await load();
    signOut.mockRejectedValueOnce(new Error("network down"));
    respondWith(() => new Response(null, { status: 401 }));
    await expect(api.listConversations()).rejects.toThrow();
    await flush();
    expect(signOut).toHaveBeenCalledTimes(1);
    await expect(api.listDocuments()).rejects.toThrow();
    await flush();
    expect(signOut).toHaveBeenCalledTimes(2);
  });
});

describe("JSON calls", () => {
  it.each([
    [
      "listConversations",
      [{ id: "c1", title: null }],
      (api: ChatApi) => api.listConversations(),
    ],
    [
      "getConversation",
      { id: "c1", title: "Hello", messages: [] },
      (api: ChatApi) => api.getConversation("c1"),
    ],
    [
      "listDocuments",
      [{ id: "d1", filename: "a.txt", status: "ready" }],
      (api: ChatApi) => api.listDocuments(),
    ],
  ])("%s resolves to the parsed body", async (_n, body, invoke) => {
    const api = await load();
    respondWith(() => jsonResponse(body));
    await expect(invoke(api)).resolves.toEqual(body);
  });

  it.each([
    ["listConversations", (api: ChatApi) => api.listConversations()],
    ["getConversation", (api: ChatApi) => api.getConversation("c1")],
    ["listDocuments", (api: ChatApi) => api.listDocuments()],
  ])("%s rejects with the status on a non-ok response", async (_n, invoke) => {
    const api = await load();
    respondWith(() => jsonResponse({ detail: "boom" }, 500));
    await expect(invoke(api)).rejects.toThrow("API 500");
  });

  it("getConversation rejects a 404: only deletes treat a 404 as success", async () => {
    const api = await load();
    respondWith(() => jsonResponse({ detail: "Not found" }, 404));
    await expect(api.getConversation("gone")).rejects.toThrow("API 404");
  });
});

describe("uploadDocument", () => {
  it("sends the file as multipart under 'file' without its own Content-Type", async () => {
    const api = await load();
    const created = { id: "d1", filename: "a.txt", status: "pending" };
    respondWith(() => jsonResponse(created, 201));
    const file = new File(["hello"], "a.txt", { type: "text/plain" });
    await expect(api.uploadDocument(file)).resolves.toEqual(created);
    const { init } = call();
    expect(init.body).toBeInstanceOf(FormData);
    const sent = (init.body as FormData).get("file");
    expect(sent).toBeInstanceOf(File);
    expect((sent as File).name).toBe("a.txt");
    expect(await (sent as File).text()).toBe("hello");
    expect(new Headers(init.headers).has("content-type")).toBe(false);
  });

  it("rejects with FastAPI's string detail", async () => {
    const api = await load();
    respondWith(() => jsonResponse({ detail: "File too large" }, 413));
    await expect(api.uploadDocument(new File(["x"], "a.txt"))).rejects.toThrow(
      "File too large",
    );
  });

  it("rejects with the field and message for a 422 validation array", async () => {
    const api = await load();
    respondWith(() =>
      jsonResponse(
        { detail: [{ loc: ["body", "file"], msg: "Field required" }] },
        422,
      ),
    );
    await expect(api.uploadDocument(new File(["x"], "a.txt"))).rejects.toThrow(
      "file: Field required",
    );
  });

  it("rejects with the status for a non-JSON body", async () => {
    const api = await load();
    respondWith(() => new Response("Bad Gateway", { status: 502 }));
    await expect(api.uploadDocument(new File(["x"], "a.txt"))).rejects.toThrow(
      "API 502",
    );
  });
});

describe.each([
  ["deleteDocument", (api: ChatApi) => api.deleteDocument("x1")],
  ["deleteConversation", (api: ChatApi) => api.deleteConversation("x1")],
])("%s", (_name, invoke) => {
  it("resolves on 204", async () => {
    const api = await load();
    respondWith(() => new Response(null, { status: 204 }));
    await expect(invoke(api)).resolves.toBeUndefined();
  });

  it("resolves on 404 because the target is already gone", async () => {
    const api = await load();
    respondWith(() => jsonResponse({ detail: "Not found" }, 404));
    await expect(invoke(api)).resolves.toBeUndefined();
  });

  it("rejects with the string detail on another failure", async () => {
    const api = await load();
    respondWith(() => jsonResponse({ detail: "Document is processing" }, 409));
    await expect(invoke(api)).rejects.toThrow("Document is processing");
  });

  it("rejects with the status when the detail is not a string", async () => {
    const api = await load();
    respondWith(() => jsonResponse({ detail: [{ msg: "bad id" }] }, 422));
    await expect(invoke(api)).rejects.toThrow("API 422");
  });

  it("rejects with the status when the body is not JSON", async () => {
    const api = await load();
    respondWith(() => new Response("oops", { status: 500 }));
    await expect(invoke(api)).rejects.toThrow("API 500");
  });
});

describe("downloadDocument", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts a browser download of the fetched blob under the given name", async () => {
    vi.useFakeTimers();
    const api = await load();
    const created: Blob[] = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      created.push(blob as Blob);
      return "blob:hax/1";
    });
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => {});
    const clicked: Array<{ download: string; href: string }> = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push({ download: this.download, href: this.href });
    });
    respondWith(
      () =>
        new Response("file bytes", {
          status: 200,
          headers: { "Content-Type": "text/plain" },
        }),
    );

    await api.downloadDocument("d1", "report.pdf");
    vi.runAllTimers();

    expect(created).toHaveLength(1);
    expect(await created[0].text()).toBe("file bytes");
    expect(clicked).toEqual([{ download: "report.pdf", href: "blob:hax/1" }]);
    expect(revoke).toHaveBeenCalledWith("blob:hax/1");
  });

  it("rejects with the status on a non-ok response", async () => {
    const api = await load();
    vi.spyOn(URL, "createObjectURL").mockImplementation(() => "blob:hax/1");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    respondWith(() => jsonResponse({ detail: "Not found" }, 404));
    await expect(api.downloadDocument("d1", "a.txt")).rejects.toThrow(
      "API 404",
    );
    expect(click).not.toHaveBeenCalled();
  });
});

describe("streamChat", () => {
  function stream(reads: Array<string | Uint8Array>): void {
    respondWith(() => sseResponse(reads));
  }

  it("posts the prompt as JSON with a null model and conversation for a new chat", async () => {
    const api = await load();
    stream([sseEvent("[DONE]")]);
    await api.streamChat("hello", null, handlers());
    const { init } = call();
    expect(new Headers(init.headers).get("content-type")).toBe(
      "application/json",
    );
    expect(JSON.parse(init.body as string)).toEqual({
      prompt: "hello",
      conversation_id: null,
      model: null,
    });
  });

  it("posts the conversation id and the chosen model", async () => {
    const api = await load();
    stream([sseEvent("[DONE]")]);
    await api.streamChat("again", "c1", handlers(), "claude-sonnet");
    expect(JSON.parse(call().init.body as string)).toEqual({
      prompt: "again",
      conversation_id: "c1",
      model: "claude-sonnet",
    });
  });

  it("posts the message id when one is given", async () => {
    const api = await load();
    stream([sseEvent("[DONE]")]);
    await api.streamChat("again", "c1", handlers(), null, "m-1");
    expect(JSON.parse(call().init.body as string)).toEqual({
      prompt: "again",
      conversation_id: "c1",
      model: null,
      message_id: "m-1",
    });
  });

  it("dispatches every event kind to its handler in stream order", async () => {
    const api = await load();
    const h = handlers();
    stream([
      sseEvent({ conversation_id: "c9" }),
      sseEvent({ status: "Searching your documents" }),
      sseEvent({ content: "Hello" }),
      sseEvent({ sources: [source] }),
      sseEvent({ content: " world" }),
      sseEvent("[DONE]"),
    ]);
    await api.streamChat("hi", null, h);
    expect(h.log).toEqual([
      ["conversation", "c9"],
      ["status", "Searching your documents"],
      ["chunk", "Hello"],
      ["sources", [source]],
      ["chunk", " world"],
    ]);
  });

  it("resolves at [DONE] with the connection still open, and nothing after it reaches a handler", async () => {
    const api = await load();
    const h = handlers();
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(sseEvent({ content: "hi" })));
        controller.enqueue(encoder.encode(sseEvent("[DONE]")));
        controller.enqueue(encoder.encode(sseEvent({ content: "after" })));
      },
    });
    respondWith(() => new Response(body, { status: 200 }));
    await api.streamChat("hi", null, h);
    expect(h.log).toEqual([["chunk", "hi"]]);
  });

  it("reassembles an event split across reads", async () => {
    const api = await load();
    const h = handlers();
    stream([
      'data: {"conte',
      'nt":"hel',
      'lo"}\n',
      "\n",
      'data: {"status":"thin',
      'king"}\n\ndata: [DO',
      "NE]\n\n",
    ]);
    await api.streamChat("hi", null, h);
    expect(h.log).toEqual([
      ["chunk", "hello"],
      ["status", "thinking"],
    ]);
  });

  it("keeps a multi-byte UTF-8 character split across reads intact", async () => {
    const api = await load();
    const h = handlers();
    const text = "café € 😀";
    const bytes = new TextEncoder().encode(
      sseEvent({ content: text }) + sseEvent("[DONE]"),
    );
    const euro = bytes.indexOf(0xe2);
    const emoji = bytes.indexOf(0xf0);
    stream([
      bytes.slice(0, euro + 1),
      bytes.slice(euro + 1, emoji + 2),
      bytes.slice(emoji + 2),
    ]);
    await api.streamChat("hi", null, h);
    expect(h.onChunk).toHaveBeenCalledTimes(1);
    expect(h.onChunk).toHaveBeenCalledWith(text);
  });

  it.each([
    ["malformed JSON", "data: {not json\n\n"],
    ["an unknown key", sseEvent({ unexpected: "x" })],
    ["a non-string content", sseEvent({ content: 42 })],
    ["an empty content", sseEvent({ content: "" })],
    ["a non-string status", sseEvent({ status: ["x"] })],
    ["an empty status", sseEvent({ status: "" })],
    ["a non-string conversation id", sseEvent({ conversation_id: 7 })],
    ["a non-array sources", sseEvent({ sources: "x" })],
    ["a JSON null", "data: null\n\n"],
    ["an SSE comment line", ": keep-alive\n\n"],
  ])("ignores %s and keeps streaming", async (_label, junk) => {
    const api = await load();
    const h = handlers();
    stream([junk, sseEvent({ content: "after" }), sseEvent("[DONE]")]);
    await api.streamChat("hi", null, h);
    expect(h.log).toEqual([["chunk", "after"]]);
  });

  it.each([
    ["a missing excerpt", { ...source, excerpt: undefined }],
    ["a string distance", { ...source, distance: "0.1" }],
    ["a string chunk index", { ...source, chunk_idx: "2" }],
    ["a null element", null],
  ])("keeps the valid sources when one element has %s", async (_label, bad) => {
    const api = await load();
    const h = handlers();
    stream([
      sseEvent({ sources: [source, bad] }),
      sseEvent({ content: "after" }),
      sseEvent("[DONE]"),
    ]);
    await api.streamChat("hi", null, h);
    expect(h.onSources).toHaveBeenCalledExactlyOnceWith([source]);
    expect(h.log).toEqual([
      ["sources", [source]],
      ["chunk", "after"],
    ]);
  });

  it.each([
    ["only invalid elements", [{ ...source, distance: "near" }, null]],
    ["an empty list", []],
  ])("skips a sources event with %s", async (_label, sources) => {
    const api = await load();
    const h = handlers();
    stream([sseEvent({ sources }), sseEvent("[DONE]")]);
    await api.streamChat("hi", null, h);
    expect(h.onSources).not.toHaveBeenCalled();
  });

  it("works without the optional status and sources handlers", async () => {
    const api = await load();
    const onConversationId = vi.fn();
    const onChunk = vi.fn();
    stream([
      sseEvent({ status: "Searching" }),
      sseEvent({ sources: [source] }),
      sseEvent({ content: "done" }),
      sseEvent("[DONE]"),
    ]);
    await expect(
      api.streamChat("hi", null, { onConversationId, onChunk }),
    ).resolves.toBeUndefined();
    expect(onChunk).toHaveBeenCalledWith("done");
  });

  it("rejects with DemoLimitError on a demo_limit 403", async () => {
    const api = await load();
    respondWith(() => jsonResponse({ detail: { code: "demo_limit" } }, 403));
    const err = await api
      .streamChat("hi", null, handlers())
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(api.DemoLimitError);
    expect((err as Error).name).toBe("DemoLimitError");
  });

  it.each([
    [403, { detail: "Forbidden" }, "Forbidden"],
    [403, { detail: { code: "something_else" } }, "API 403"],
    [500, { detail: "Internal Server Error" }, "Internal Server Error"],
  ])(
    "rejects a %i that is not a demo limit with a plain error (%j)",
    async (status, body, message) => {
      const api = await load();
      respondWith(() => jsonResponse(body, status));
      const err = await api
        .streamChat("hi", null, handlers())
        .catch((e: unknown) => e);
      expect(err).toBeInstanceOf(Error);
      expect((err as Error).message).toContain(message);
      expect(err).not.toBeInstanceOf(api.DemoLimitError);
    },
  );

  it("rejects a 409 with TurnInProgressError carrying the server's detail", async () => {
    const api = await load();
    const detail = "A reply is already in progress in this conversation.";
    respondWith(() => jsonResponse({ detail }, 409));
    const h = handlers();
    const err = await api.streamChat("hi", "c1", h).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(api.TurnInProgressError);
    expect((err as Error).name).toBe("TurnInProgressError");
    expect((err as Error).message).toBe(detail);
    expect(err).not.toBeInstanceOf(api.DemoLimitError);
    expect(h.log).toEqual([]);
  });

  it("rejects another non-ok status with its string detail as the message", async () => {
    const api = await load();
    respondWith(() =>
      jsonResponse({ detail: "The model is busy, try again." }, 503),
    );
    const err = await api
      .streamChat("hi", null, handlers())
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe("The model is busy, try again.");
    expect(err).not.toBeInstanceOf(api.TurnInProgressError);
    expect(err).not.toBeInstanceOf(api.DemoLimitError);
  });

  it("rejects a non-JSON error body with the status and status text", async () => {
    const api = await load();
    respondWith(
      () =>
        new Response("<html>Bad Gateway</html>", {
          status: 502,
          statusText: "Bad Gateway",
        }),
    );
    const err = await api
      .streamChat("hi", null, handlers())
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe("API 502: Bad Gateway");
    expect(err).not.toBeInstanceOf(api.TurnInProgressError);
  });

  it("rejects a 422 validation array with the field and message", async () => {
    const api = await load();
    respondWith(
      () =>
        new Response(
          JSON.stringify({
            detail: [{ loc: ["body", "prompt"], msg: "Field required" }],
          }),
          {
            status: 422,
            statusText: "Unprocessable Entity",
            headers: { "Content-Type": "application/json" },
          },
        ),
    );
    const err = await api
      .streamChat("hi", null, handlers())
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe("prompt: Field required");
    expect(err).not.toBeInstanceOf(api.TurnInProgressError);
  });
});

describe("streamChat reply failure", () => {
  function stream(reads: Array<string | Uint8Array>): void {
    respondWith(() => sseResponse(reads));
  }

  async function rejection(promise: Promise<unknown>): Promise<unknown> {
    return promise.then(
      () => {
        throw new Error("expected streamChat to reject");
      },
      (err: unknown) => err,
    );
  }

  it("delivers every event before an error frame, then rejects with ReplyFailedError", async () => {
    const api = await load();
    const h = handlers();
    stream([
      sseEvent({ conversation_id: "c1" }),
      sseEvent({ status: "Searching your documents" }),
      sseEvent({ content: "Hello" }),
      sseEvent({ sources: [source] }),
      sseEvent({ content: " wor" }),
      sseEvent({ error: "reply_failed" }),
    ]);
    const err = await rejection(api.streamChat("hi", null, h));
    expect(err).toBeInstanceOf(api.ReplyFailedError);
    expect(h.log).toEqual([
      ["conversation", "c1"],
      ["status", "Searching your documents"],
      ["chunk", "Hello"],
      ["sources", [source]],
      ["chunk", " wor"],
    ]);
  });

  it("a ReplyFailedError is named ReplyFailedError and carries the frame's code as its message", async () => {
    const api = await load();
    stream([sseEvent({ error: "reply_failed" })]);
    const err = await rejection(api.streamChat("hi", null, handlers()));
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).name).toBe("ReplyFailedError");
    expect((err as Error).message).toBe("reply_failed");
  });

  it("an error frame with any string code rejects with ReplyFailedError", async () => {
    const api = await load();
    stream([sseEvent({ content: "x" }), sseEvent({ error: "some_new_code" })]);
    const err = await rejection(api.streamChat("hi", null, handlers()));
    expect(err).toBeInstanceOf(api.ReplyFailedError);
    expect((err as Error).message).toBe("some_new_code");
  });

  it("an event carrying both an error code and content is a failure and its content is not delivered", async () => {
    const api = await load();
    const h = handlers();
    stream([
      sseEvent({ content: "before" }),
      sseEvent({ error: "reply_failed", content: "not shown" }),
    ]);
    const err = await rejection(api.streamChat("hi", null, h));
    expect(err).toBeInstanceOf(api.ReplyFailedError);
    expect(h.log).toEqual([["chunk", "before"]]);
  });

  it("nothing after an error frame reaches a handler", async () => {
    const api = await load();
    const h = handlers();
    stream([
      sseEvent({ content: "before" }),
      sseEvent({ error: "reply_failed" }),
      sseEvent({ content: "after" }),
      sseEvent("[DONE]"),
    ]);
    const err = await rejection(api.streamChat("hi", null, h));
    expect(err).toBeInstanceOf(api.ReplyFailedError);
    expect(h.log).toEqual([["chunk", "before"]]);
  });

  it("rejects at an error frame with the connection still open, without cancelling the stream", async () => {
    const api = await load();
    const h = handlers();
    const cancel = vi.fn();
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(sseEvent({ content: "hi" })));
        controller.enqueue(encoder.encode(sseEvent({ error: "reply_failed" })));
      },
      cancel,
    });
    respondWith(() => new Response(body, { status: 200 }));
    const outcome = await Promise.race([
      rejection(api.streamChat("hi", null, h)),
      new Promise((resolve) => setTimeout(() => resolve("still pending"), 500)),
    ]);
    expect(outcome).toBeInstanceOf(api.ReplyFailedError);
    expect(h.log).toEqual([["chunk", "hi"]]);
    await flush();
    expect(cancel).not.toHaveBeenCalled();
  });

  it("an error frame left in the trailing buffer at EOF rejects with ReplyFailedError after the events before it", async () => {
    const api = await load();
    const h = handlers();
    stream([sseEvent({ content: "first" }), 'data: {"error":"reply_failed"}']);
    const err = await rejection(api.streamChat("hi", null, h));
    expect(err).toBeInstanceOf(api.ReplyFailedError);
    expect((err as Error).message).toBe("reply_failed");
    expect(h.log).toEqual([["chunk", "first"]]);
  });

  it("[DONE] after content still resolves", async () => {
    const api = await load();
    const h = handlers();
    stream([
      sseEvent({ content: "Hello" }),
      sseEvent({ content: " world" }),
      sseEvent("[DONE]"),
    ]);
    await expect(api.streamChat("hi", null, h)).resolves.toBeUndefined();
    expect(h.log).toEqual([
      ["chunk", "Hello"],
      ["chunk", " world"],
    ]);
  });
});

describe("streamChat lost connection", () => {
  const SILENCE_MS = 45_000;

  function stream(reads: Array<string | Uint8Array>): void {
    respondWith(() => sseResponse(reads));
  }

  async function rejection(promise: Promise<unknown>): Promise<unknown> {
    return promise.then(
      () => {
        throw new Error("expected streamChat to reject");
      },
      (err: unknown) => err,
    );
  }

  // A response body the test feeds by hand and can break or leave silent.
  function openStream() {
    const encoder = new TextEncoder();
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const cancelled = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
      },
      cancel: cancelled,
    });
    respondWith(
      () =>
        new Response(body, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
    );
    return {
      push: (text: string) => controller.enqueue(encoder.encode(text)),
      fail: (reason: unknown) => controller.error(reason),
      cancelled,
    };
  }

  afterEach(() => {
    vi.useRealTimers();
  });

  it("ConnectionLostError is an Error named ConnectionLostError", async () => {
    const api = await load();
    const err = new api.ConnectionLostError();
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ConnectionLostError");
  });

  it("a read that rejects after the response started rejects with ConnectionLostError after the events before it", async () => {
    const api = await load();
    const h = handlers();
    const body = openStream();
    const settled = rejection(api.streamChat("hi", "c1", h));
    body.push(sseEvent({ conversation_id: "c1" }));
    body.push(sseEvent({ content: "partial" }));
    await flush();
    body.fail(new TypeError("network error"));
    const err = await settled;
    expect(err).toBeInstanceOf(api.ConnectionLostError);
    expect(h.log).toEqual([
      ["conversation", "c1"],
      ["chunk", "partial"],
    ]);
  });

  it("EOF without [DONE] or an error frame rejects with ConnectionLostError", async () => {
    const api = await load();
    const h = handlers();
    stream([
      sseEvent({ conversation_id: "c1" }),
      sseEvent({ content: "partial" }),
    ]);
    const err = await rejection(api.streamChat("hi", "c1", h));
    expect(err).toBeInstanceOf(api.ConnectionLostError);
    expect(err).not.toBeInstanceOf(api.ReplyFailedError);
    expect(h.log).toEqual([
      ["conversation", "c1"],
      ["chunk", "partial"],
    ]);
  });

  it("a response that ends with no bytes at all rejects with ConnectionLostError", async () => {
    const api = await load();
    stream([]);
    const err = await rejection(api.streamChat("hi", "c1", handlers()));
    expect(err).toBeInstanceOf(api.ConnectionLostError);
  });

  it("a final event without its blank line is a cut connection: not delivered, and ConnectionLostError", async () => {
    const api = await load();
    const h = handlers();
    stream([sseEvent({ content: "first" }), 'data: {"content":"tail"}']);
    const err = await rejection(api.streamChat("hi", null, h));
    expect(err).toBeInstanceOf(api.ConnectionLostError);
    expect(h.log).toEqual([["chunk", "first"]]);
  });

  it("a fetch rejected before any response is not a ConnectionLostError", async () => {
    const api = await load();
    fetchMock.mockImplementation(async () => {
      throw new TypeError("Failed to fetch");
    });
    const err = await rejection(api.streamChat("hi", "c1", handlers()));
    expect(err).not.toBeInstanceOf(api.ConnectionLostError);
  });

  it("keepalive comment lines reach no handler and the stream still resolves at [DONE]", async () => {
    const api = await load();
    const h = handlers();
    stream([
      sseEvent({ conversation_id: "c1" }),
      ": keepalive\n\n",
      sseEvent({ content: "Hello" }),
      ": keepalive\n\n",
      sseEvent("[DONE]"),
    ]);
    await api.streamChat("hi", "c1", h);
    expect(h.log).toEqual([
      ["conversation", "c1"],
      ["chunk", "Hello"],
    ]);
  });

  it("45 silent seconds after the response started reject with ConnectionLostError and cancel the reader", async () => {
    vi.useFakeTimers();
    const api = await load();
    const h = handlers();
    const body = openStream();
    let outcome: unknown = "pending";
    void api.streamChat("hi", "c1", h).then(
      () => {
        outcome = "resolved";
      },
      (err: unknown) => {
        outcome = err;
      },
    );
    body.push(sseEvent({ conversation_id: "c1" }));
    body.push(sseEvent({ content: "partial" }));
    await vi.advanceTimersByTimeAsync(0);
    expect(h.log).toEqual([
      ["conversation", "c1"],
      ["chunk", "partial"],
    ]);

    await vi.advanceTimersByTimeAsync(SILENCE_MS - 1_000);
    expect(outcome).toBe("pending");

    await vi.advanceTimersByTimeAsync(2_000);
    expect(outcome).toBeInstanceOf(api.ConnectionLostError);
    expect(body.cancelled).toHaveBeenCalled();
  });

  it("45 seconds with no response headers abort the request with an AbortError, not a ConnectionLostError", async () => {
    vi.useFakeTimers();
    const api = await load();
    fetchMock.mockImplementation(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(
              new DOMException("The operation was aborted.", "AbortError"),
            ),
          );
        }),
    );
    let outcome: unknown = "pending";
    void api.streamChat("hi", "c1", handlers()).then(
      () => {
        outcome = "resolved";
      },
      (err: unknown) => {
        outcome = err;
      },
    );

    await vi.advanceTimersByTimeAsync(SILENCE_MS - 1_000);
    expect(outcome).toBe("pending");

    await vi.advanceTimersByTimeAsync(2_000);
    expect((outcome as { name?: unknown }).name).toBe("AbortError");
    expect(outcome).not.toBeInstanceOf(api.ConnectionLostError);
  });

  it("keepalives more often than every 45 seconds keep a long reply alive until [DONE]", async () => {
    vi.useFakeTimers();
    const api = await load();
    const h = handlers();
    const body = openStream();
    let outcome: unknown = "pending";
    void api.streamChat("hi", "c1", h).then(
      () => {
        outcome = "resolved";
      },
      (err: unknown) => {
        outcome = err;
      },
    );
    body.push(sseEvent({ conversation_id: "c1" }));
    await vi.advanceTimersByTimeAsync(0);
    for (let i = 0; i < 6; i++) {
      await vi.advanceTimersByTimeAsync(30_000);
      body.push(": keepalive\n\n");
    }
    await vi.advanceTimersByTimeAsync(30_000);
    expect(outcome).toBe("pending");

    body.push(sseEvent({ content: "late answer" }));
    body.push(sseEvent("[DONE]"));
    await vi.advanceTimersByTimeAsync(0);
    expect(outcome).toBe("resolved");
    expect(h.log).toEqual([
      ["conversation", "c1"],
      ["chunk", "late answer"],
    ]);
    expect(body.cancelled).not.toHaveBeenCalled();
  });
});

describe("error detail from a FastAPI validation array", () => {
  function failWith(body: string, status = 422, statusText = "Unprocessable Entity"): void {
    respondWith(
      () =>
        new Response(body, {
          status,
          statusText,
          headers: { "Content-Type": "application/json" },
        }),
    );
  }

  it("names the last loc element before the message", async () => {
    const api = await load();
    const detail = [
      { loc: ["body", "message_id"], msg: "Input should be a valid UUID", type: "uuid_parsing" },
    ];
    failWith(JSON.stringify({ detail }));
    const err = await api.deleteConversation("c1").catch((e: unknown) => e);
    expect((err as Error).message).toBe("message_id: Input should be a valid UUID");
  });

  it("joins several items with '; ' in order, a one-element loc giving the bare message", async () => {
    const api = await load();
    const detail = [
      { loc: ["body"], msg: "Field required", type: "missing" },
      { loc: ["query", "limit"], msg: "Input should be a valid integer", type: "int_parsing" },
    ];
    failWith(JSON.stringify({ detail }));
    const err = await api.deleteDocument("d1").catch((e: unknown) => e);
    expect((err as Error).message).toBe("Field required; limit: Input should be a valid integer");
  });

  it("keeps a string detail unchanged", async () => {
    const api = await load();
    failWith(JSON.stringify({ detail: "Document is processing" }), 409, "Conflict");
    const err = await api.deleteDocument("d1").catch((e: unknown) => e);
    expect((err as Error).message).toBe("Document is processing");
  });

  it("falls back to the status and status text for a non-JSON body", async () => {
    const api = await load();
    failWith("<html>nope</html>");
    const err = await api.deleteConversation("c1").catch((e: unknown) => e);
    expect((err as Error).message).toBe("API 422: Unprocessable Entity");
  });
});
