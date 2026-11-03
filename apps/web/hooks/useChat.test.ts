import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ConversationDetail,
  getConversation as GetConversationFn,
  Source,
  StreamHandlers,
  streamChat as StreamChatFn,
  streamRetry as StreamRetryFn,
} from "@/lib/chatApi";
import {
  AlreadyAnsweredError,
  ConnectionLostError,
  NothingToRetryError,
  ReplyFailedError,
  ReplyRefusedError,
  TurnInProgressError,
} from "@/lib/chatApi";
import { useChat } from "@/hooks/useChat";

const { getConversation, streamChat, streamRetry, DemoLimitError } = vi.hoisted(
  () => ({
    getConversation: vi.fn<typeof GetConversationFn>(),
    streamChat: vi.fn<typeof StreamChatFn>(),
    streamRetry: vi.fn<typeof StreamRetryFn>(),
    DemoLimitError: class DemoLimitError extends Error {
      constructor() {
        super("demo_limit");
        this.name = "DemoLimitError";
      }
    },
  }),
);
vi.mock("@/lib/chatApi", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/chatApi")>("@/lib/chatApi");
  return {
    getConversation,
    streamChat,
    streamRetry,
    DemoLimitError,
    TurnInProgressError: actual.TurnInProgressError,
    NothingToRetryError: actual.NothingToRetryError,
    AlreadyAnsweredError: actual.AlreadyAnsweredError,
    ReplyFailedError: actual.ReplyFailedError,
    ReplyRefusedError: actual.ReplyRefusedError,
    ConnectionLostError: actual.ConnectionLostError,
    // The real request over a stubbed fetch: the hook tells an HTTP failure
    // from a network one by what stopReply rejects with.
    stopReply: actual.stopReply,
  };
});

type Turn = {
  handlers: StreamHandlers;
  end: () => void;
  fail: (reason: unknown) => void;
};

// The next streamChat call stays in flight until the test ends or fails it.
function holdTurn(): Turn {
  const turn = {} as Turn;
  streamChat.mockImplementationOnce(
    (_prompt, _conversationId, handlers) =>
      new Promise<void>((resolve, reject) => {
        turn.handlers = handlers;
        turn.end = () => resolve();
        turn.fail = reject;
      }),
  );
  return turn;
}

function detail(
  id: string,
  messages: ConversationDetail["messages"],
): ConversationDetail {
  return {
    id,
    title: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    replying: false,
    messages,
  };
}

function source(document_id: string, chunk_idx: number): Source {
  return {
    document_id,
    filename: `${document_id}.txt`,
    chunk_idx,
    excerpt: `${document_id} passage ${chunk_idx}`,
    distance: 0.1,
  };
}

// send() starts the turn inside act so the in-flight state can be observed;
// `settled` is awaited later, after the test has driven the stream.
async function start(
  result: { current: ReturnType<typeof useChat> },
  text: string,
): Promise<{ settled: Promise<void> }> {
  let settled!: Promise<void>;
  await act(async () => {
    settled = result.current.send(text);
  });
  return { settled };
}

async function settle(settled: Promise<void>, finish: () => void) {
  await act(async () => {
    finish();
    await settled;
  });
}

async function newChatTurn(
  turn: Turn,
  events: (handlers: StreamHandlers) => void,
  outcome: (turn: Turn) => void = (t) => t.end(),
  callbacks: { onTurnComplete?: () => void } = {},
) {
  const hook = renderHook(() =>
    useChat(null, null, undefined, callbacks.onTurnComplete),
  );
  const { settled } = await start(hook.result, "hi");
  act(() => events(turn.handlers));
  await settle(settled, () => outcome(turn));
  return hook.result;
}

describe("useChat loading", () => {
  it("a new chat starts empty without loading anything", () => {
    const { result } = renderHook(() => useChat(null, null));
    expect(result.current.messages).toEqual([]);
    expect(getConversation).not.toHaveBeenCalled();
  });

  it("an existing conversation shows its loaded messages, null sources as none", async () => {
    getConversation.mockResolvedValue(
      detail("c1", [
        {
          id: "m1",
          role: "user",
          content: "question",
          created_at: "2026-10-01T00:00:01Z",
          sources: null,
        },
        {
          id: "m2",
          role: "assistant",
          content: "answer",
          created_at: "2026-10-01T00:00:02Z",
          sources: [source("d1", 0)],
        },
      ]),
    );
    const { result } = renderHook(() => useChat("c1", null));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(getConversation).toHaveBeenCalledExactlyOnceWith("c1");
    expect(result.current.messages[0]).toEqual({
      id: "m1",
      role: "user",
      content: "question",
      created_at: "2026-10-01T00:00:01Z",
    });
    expect(result.current.messages[1]).toEqual({
      id: "m2",
      role: "assistant",
      content: "answer",
      created_at: "2026-10-01T00:00:02Z",
      sources: [source("d1", 0)],
    });
  });

  it("loaded messages keep the server's message ids, in order", async () => {
    getConversation.mockResolvedValue(
      detail("c1", [
        {
          id: "u-1",
          role: "user",
          content: "first question",
          created_at: "2026-10-01T00:00:01Z",
        },
        {
          id: "a-1",
          role: "assistant",
          content: "first answer",
          created_at: "2026-10-01T00:00:02Z",
        },
        {
          id: "u-2",
          role: "user",
          content: "second question",
          created_at: "2026-10-01T00:00:03Z",
        },
      ]),
    );
    const { result } = renderHook(() => useChat("c1", null));
    await waitFor(() => expect(result.current.messages).toHaveLength(3));
    expect(result.current.messages.map((m) => m.id)).toEqual([
      "u-1",
      "a-1",
      "u-2",
    ]);
  });

  it("a failed load shows the load error", async () => {
    getConversation.mockRejectedValue(new Error("API 500"));
    const { result } = renderHook(() => useChat("c1", null));
    await waitFor(() =>
      expect(result.current.error).toBe("Couldn't load this conversation."),
    );
  });

  it.each([
    ["after", ["b", "a"] as const],
    ["before", ["a", "b"] as const],
  ])(
    "an earlier load never shows when it resolves %s the newer one",
    async (_label, order) => {
      const resolvers: Record<string, (d: ConversationDetail) => void> = {};
      getConversation.mockImplementation(
        (id) => new Promise((r) => (resolvers[id] = r)),
      );
      const message = (
        content: string,
      ): ConversationDetail["messages"][number] => ({
        id: content,
        role: "user",
        content,
        created_at: "2026-10-01T00:00:01Z",
      });
      const { result, rerender } = renderHook(
        ({ id }: { id: string }) => useChat(id, null),
        { initialProps: { id: "a" } },
      );
      rerender({ id: "b" });
      for (const id of order) {
        await act(async () => resolvers[id](detail(id, [message(id)])));
        expect(result.current.messages.map((m) => m.content)).not.toContain(
          "a",
        );
      }
      expect(result.current.messages.map((m) => m.content)).toEqual(["b"]);
    },
  );
});

describe("useChat sending", () => {
  it("a whitespace-only text sends nothing", async () => {
    const { result } = renderHook(() => useChat(null, null));
    await act(() => result.current.send("  \n\t "));
    expect(streamChat).not.toHaveBeenCalled();
    expect(result.current.messages).toEqual([]);
  });

  it("a send while a turn is in flight does nothing", async () => {
    const turn = holdTurn();
    const { result } = renderHook(() => useChat(null, null));
    const { settled } = await start(result, "first");
    await act(() => result.current.send("second"));
    expect(streamChat).toHaveBeenCalledTimes(1);
    expect(result.current.messages).toHaveLength(1);
    await settle(settled, () => turn.end());
  });

  it("the trimmed user message shows at once, loading starts, and an earlier error clears", async () => {
    streamChat.mockRejectedValueOnce(new Error("boom"));
    const turn = holdTurn();
    const { result } = renderHook(() => useChat(null, null));
    await act(() => result.current.send("first"));
    expect(result.current.error).toBe("boom");

    const { settled } = await start(result, "  second  ");
    expect(result.current.isLoading).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.messages.at(-1)).toEqual({
      id: expect.any(String),
      role: "user",
      content: "second",
      created_at: expect.any(String),
    });
    await settle(settled, () => turn.end());
  });

  it.each([
    ["a new chat targets no conversation", null, null],
    [
      "an existing chat targets its conversation and passes the model",
      "c1",
      "model-x",
    ],
  ])("%s", async (_label, conversationId, model) => {
    getConversation.mockResolvedValue(detail("c1", []));
    streamChat.mockResolvedValue();
    const { result } = renderHook(() => useChat(conversationId, model));
    if (conversationId) {
      await waitFor(() => expect(getConversation).toHaveBeenCalled());
      await act(async () => {});
    }
    await act(() => result.current.send("  hi  "));
    expect(streamChat).toHaveBeenCalledExactlyOnceWith(
      "hi",
      conversationId,
      expect.any(Object),
      model,
      expect.any(String),
    );
  });

  it("the optimistic user turn carries the same id the send passes as its message id", async () => {
    const turn = holdTurn();
    const { result } = renderHook(() => useChat(null, null));
    const { settled } = await start(result, "hi");
    const sentId = streamChat.mock.calls[0][4];
    expect(sentId).toEqual(expect.any(String));
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].id).toBe(sentId);
    await settle(settled, () => turn.end());
    expect(result.current.messages[0].id).toBe(sentId);
  });

  it("two sends give their user turns different ids", async () => {
    const { result } = renderHook(() => useChat(null, null));
    for (const text of ["one", "two"]) {
      const turn = holdTurn();
      const { settled } = await start(result, text);
      act(() => {
        turn.handlers.onConversationId("c1");
        turn.handlers.onChunk(`reply to ${text}`);
      });
      await settle(settled, () => turn.end());
    }
    const users = result.current.messages.filter((m) => m.role === "user");
    expect(users).toHaveLength(2);
    expect(users[0].id).toEqual(expect.any(String));
    expect(users[1].id).toEqual(expect.any(String));
    expect(users[0].id).not.toBe(users[1].id);
    expect(users.map((m) => m.id)).toEqual(
      streamChat.mock.calls.map((call) => call[4]),
    );
  });

  it("chunks stream into streamingContent, then commit as one assistant message", async () => {
    const turn = holdTurn();
    const { result } = renderHook(() => useChat(null, null));
    const { settled } = await start(result, "hi");
    act(() => turn.handlers.onChunk("Hello"));
    expect(result.current.streamingContent).toBe("Hello");
    act(() => turn.handlers.onChunk(" world"));
    expect(result.current.streamingContent).toBe("Hello world");
    expect(result.current.messages).toHaveLength(1);

    await settle(settled, () => turn.end());
    expect(result.current.streamingContent).toBe("");
    expect(result.current.isLoading).toBe(false);
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1]).toMatchObject({
      role: "assistant",
      content: "Hello world",
    });
  });

  it("status shows the latest tool note, clears on reply text, and is null after the turn", async () => {
    const turn = holdTurn();
    const { result } = renderHook(() => useChat(null, null));
    const { settled } = await start(result, "hi");
    act(() => turn.handlers.onStatus?.("Searching your documents"));
    expect(result.current.status).toBe("Searching your documents");
    act(() => turn.handlers.onChunk("Found"));
    expect(result.current.status).toBeNull();
    act(() => turn.handlers.onStatus?.("Calculating"));
    expect(result.current.status).toBe("Calculating");

    await settle(settled, () => turn.end());
    expect(result.current.status).toBeNull();
  });

  it("sources from every event commit de-duplicated in first-seen order", async () => {
    const result = await newChatTurn(holdTurn(), (h) => {
      h.onSources?.([source("d1", 0), source("d2", 3)]);
      h.onChunk("answer");
      h.onSources?.([
        source("d2", 3),
        source("d1", 1),
        { ...source("d1", 0), distance: 0.9 },
      ]);
    });
    expect(result.current.messages[1].sources).toEqual([
      source("d1", 0),
      source("d2", 3),
      source("d1", 1),
    ]);
  });

  it("a turn without sources commits no sources", async () => {
    const result = await newChatTurn(holdTurn(), (h) => h.onChunk("answer"));
    expect(result.current.messages[1].role).toBe("assistant");
    expect(result.current.messages[1].sources).toBeUndefined();
  });

  it("a new chat reports its id once and the next send targets it", async () => {
    const onCreated = vi.fn();
    const { result } = renderHook(() => useChat(null, null, onCreated));
    for (const text of ["first", "second"]) {
      const turn = holdTurn();
      const { settled } = await start(result, text);
      act(() => {
        turn.handlers.onConversationId("c-new");
        turn.handlers.onChunk("ok");
      });
      await settle(settled, () => turn.end());
    }
    expect(onCreated).toHaveBeenCalledExactlyOnceWith("c-new");
    expect(streamChat.mock.calls[1][1]).toBe("c-new");
  });

  it("an existing conversation never reports a created id", async () => {
    getConversation.mockResolvedValue(detail("c1", []));
    const onCreated = vi.fn();
    const turn = holdTurn();
    const { result } = renderHook(() => useChat("c1", null, onCreated));
    await waitFor(() => expect(getConversation).toHaveBeenCalled());
    await act(async () => {});
    const { settled } = await start(result, "hi");
    act(() => {
      turn.handlers.onConversationId("c1");
      turn.handlers.onChunk("ok");
    });
    await settle(settled, () => turn.end());
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("a completed turn calls onTurnComplete once", async () => {
    const onTurnComplete = vi.fn();
    await newChatTurn(holdTurn(), (h) => h.onChunk("ok"), undefined, {
      onTurnComplete,
    });
    expect(onTurnComplete).toHaveBeenCalledOnce();
  });

  it("a lost connection shows Still answering and drops the partial", async () => {
    getConversation.mockResolvedValue({
      ...detail("new-1", []),
      replying: true,
    });
    const turn = holdTurn();
    const hook = renderHook(() => useChat(null, null));
    await start(hook.result, "hi");
    act(() => {
      turn.handlers.onConversationId("new-1");
      turn.handlers.onChunk("partial");
    });
    await act(async () => {
      turn.fail(new ConnectionLostError());
    });
    expect(hook.result.current.stillAnswering).toBe(true);
    expect(hook.result.current.streamingContent).toBe("");
    expect(hook.result.current.messages.map((m) => m.role)).toEqual(["user"]);
    expect(hook.result.current.error).toBeNull();
    expect(hook.result.current.isLoading).toBe(true);
    hook.unmount();
  });

  it("a stream error before any text adds no assistant message", async () => {
    const result = await newChatTurn(
      holdTurn(),
      () => {},
      (t) => t.fail(new Error("boom")),
    );
    expect(result.current.error).toBe("boom");
    expect(result.current.isLoading).toBe(false);
    expect(result.current.messages.map((m) => m.role)).toEqual(["user"]);
  });

  it("the demo limit removes the user message and sets limited, not error", async () => {
    const onTurnComplete = vi.fn();
    const result = await newChatTurn(
      holdTurn(),
      () => {},
      (t) => t.fail(new DemoLimitError()),
      { onTurnComplete },
    );
    expect(onTurnComplete).not.toHaveBeenCalled();
    expect(result.current.limited).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.messages).toEqual([]);
  });

  it("a reply already in progress removes the user message and shows the server's message, not the demo limit", async () => {
    const message = "A reply is already in progress in this conversation.";
    const onTurnComplete = vi.fn();
    const result = await newChatTurn(
      holdTurn(),
      () => {},
      (t) => t.fail(new TurnInProgressError(message)),
      { onTurnComplete },
    );
    expect(onTurnComplete).not.toHaveBeenCalled();
    expect(result.current.messages).toEqual([]);
    expect(result.current.error).toBe(message);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.limited).toBe(false);
    expect(result.current.streamingContent).toBe("");
  });

  it.each([
    [
      "a reply in progress",
      () =>
        new TurnInProgressError(
          "A reply is already in progress in this conversation.",
        ),
    ],
    ["the demo limit", () => new DemoLimitError()],
  ])(
    "a history load landing mid-send keeps every loaded message when %s refuses the send",
    async (_label, refusal) => {
      let loaded!: (d: ConversationDetail) => void;
      getConversation.mockImplementation(
        () => new Promise((r) => (loaded = r)),
      );
      const turn = holdTurn();
      const { result } = renderHook(() => useChat("c1", null));
      await waitFor(() => expect(getConversation).toHaveBeenCalled());

      const { settled } = await start(result, "refused text");
      await act(async () =>
        loaded(
          detail("c1", [
            {
              id: "m1",
              role: "user",
              content: "question",
              created_at: "2026-10-01T00:00:01Z",
              sources: null,
            },
            {
              id: "m2",
              role: "assistant",
              content: "answer",
              created_at: "2026-10-01T00:00:02Z",
              sources: null,
            },
          ]),
        ),
      );
      await settle(settled, () => turn.fail(refusal()));

      expect(
        result.current.messages.map(({ role, content }) => ({ role, content })),
      ).toEqual([
        { role: "user", content: "question" },
        { role: "assistant", content: "answer" },
      ]);
    },
  );

  it("a non-Error rejection shows the generic error", async () => {
    const result = await newChatTurn(
      holdTurn(),
      () => {},
      (t) => t.fail("nope"),
    );
    expect(result.current.error).toBe("Unable to get response.");
  });
});

describe("useChat reply failure", () => {
  const INTERRUPTED = "The reply was interrupted.";

  function transcript(result: { current: ReturnType<typeof useChat> }) {
    return result.current.messages.map((m) => [m.role, m.content]);
  }

  it("a reply failure before any text shows 'The reply was interrupted.' and keeps the user message", async () => {
    const turn = holdTurn();
    const result = await newChatTurn(
      turn,
      () => {},
      (t) => t.fail(new ReplyFailedError("reply_failed")),
    );
    expect(result.current.error).toBe(INTERRUPTED);
    expect(transcript(result)).toEqual([["user", "hi"]]);
    expect(result.current.streamingContent).toBe("");
    expect(result.current.status).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it("a reply failure after text shows 'The reply was interrupted.', keeps the user message and drops the partial", async () => {
    const turn = holdTurn();
    const result = await newChatTurn(
      turn,
      (h) => {
        h.onChunk("Half an ");
        h.onChunk("answer");
      },
      (t) => t.fail(new ReplyFailedError("reply_failed")),
    );
    expect(result.current.error).toBe(INTERRUPTED);
    expect(transcript(result)).toEqual([["user", "hi"]]);
    expect(
      result.current.messages.some((m) => m.content.includes("Half an")),
    ).toBe(false);
  });

  it("a reply failure after text clears the streaming text and the status and stops loading", async () => {
    const turn = holdTurn();
    const result = await newChatTurn(
      turn,
      (h) => {
        h.onChunk("Half an answer");
        h.onStatus?.("Searching your documents");
      },
      (t) => t.fail(new ReplyFailedError("reply_failed")),
    );
    expect(result.current.streamingContent).toBe("");
    expect(result.current.status).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it("a reply failure never shows the frame's code", async () => {
    const turn = holdTurn();
    const result = await newChatTurn(
      turn,
      (h) => h.onChunk("partial"),
      (t) => t.fail(new ReplyFailedError("some_new_code")),
    );
    expect(result.current.error).toBe(INTERRUPTED);
  });

  it("a reply failure after text does not call onTurnComplete", async () => {
    const turn = holdTurn();
    const onTurnComplete = vi.fn();
    await newChatTurn(
      turn,
      (h) => h.onChunk("partial"),
      (t) => t.fail(new ReplyFailedError("reply_failed")),
      { onTurnComplete },
    );
    expect(onTurnComplete).not.toHaveBeenCalled();
  });

  it("a reply failure before any text does not call onTurnComplete", async () => {
    const turn = holdTurn();
    const onTurnComplete = vi.fn();
    await newChatTurn(
      turn,
      () => {},
      (t) => t.fail(new ReplyFailedError("reply_failed")),
      { onTurnComplete },
    );
    expect(onTurnComplete).not.toHaveBeenCalled();
  });
});

describe("useChat still answering", () => {
  const INTERRUPTED = "The reply was interrupted.";
  const NOT_SENT =
    "Your message wasn't sent. Check your connection and try again.";
  const TAKING_LONGER =
    "This reply is taking longer than usual. Reload to check on it.";
  const POLL_MS = 2_000;

  afterEach(() => {
    vi.useRealTimers();
  });

  // Server timestamps, seconds past 10:00:00 on the fixture's day.
  function at(second: number): string {
    return new Date(Date.UTC(2026, 9, 1, 10, 0, second)).toISOString();
  }

  function msg(
    role: "user" | "assistant",
    content: string,
    second: number,
  ): ConversationDetail["messages"][number] {
    return {
      id: `${role}-${second}`,
      role,
      content,
      created_at: at(second),
      sources: null,
    };
  }

  function conv(
    id: string,
    messages: ConversationDetail["messages"],
    replying = false,
  ): ConversationDetail {
    return { ...detail(id, messages), replying };
  }

  type Answer = ConversationDetail | Error | Promise<ConversationDetail>;

  // GET /api/conversations/:id as the hook sees it, re-pointed per phase.
  function serve(answer: (id: string) => Answer) {
    getConversation.mockImplementation(async (id: string) => {
      const a = await answer(id);
      if (a instanceof Error) throw a;
      return a;
    });
  }

  function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((r) => {
      resolve = r;
    });
    return { promise, resolve };
  }

  async function tick(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  function transcript(result: { current: ReturnType<typeof useChat> }) {
    return result.current.messages.map((m) => [m.role, m.content]);
  }

  function polls(id: string): number {
    return getConversation.mock.calls.filter(([polled]) => polled === id)
      .length;
  }

  // The id the hook chose for its latest send, as streamChat received it.
  function sentId(): string {
    const id = streamChat.mock.calls.at(-1)?.[4];
    if (!id) throw new Error("no message id was sent");
    return id;
  }

  // The latest send's user message as the server stores it.
  function sent(
    content: string,
    second: number,
  ): ConversationDetail["messages"][number] {
    return { ...msg("user", content, second), id: sentId() };
  }

  const EARLIER = [msg("user", "earlier", 0), msg("assistant", "answer", 5)];

  async function loaded(
    id: string,
    first: ConversationDetail | Error,
    onTurnComplete?: () => void,
  ) {
    vi.useFakeTimers();
    serve(() => first);
    const hook = renderHook(() => useChat(id, null, undefined, onTurnComplete));
    await tick(0);
    return hook;
  }

  async function lose(turn: Turn, reason: unknown) {
    await act(async () => {
      turn.fail(reason);
      await vi.advanceTimersByTimeAsync(0);
    });
  }

  describe("on load", () => {
    it("a conversation loaded while replying is stillAnswering with the composer busy, and polls every 2 seconds", async () => {
      const { result, unmount } = await loaded(
        "c1",
        conv("c1", [msg("user", "q", 0)], true),
      );
      expect(result.current.stillAnswering).toBe(true);
      expect(result.current.isLoading).toBe(true);
      expect(result.current.error).toBeNull();
      expect(transcript(result)).toEqual([["user", "q"]]);

      await tick(POLL_MS);
      const afterFirstTick = polls("c1");
      expect(afterFirstTick).toBeGreaterThan(1);
      await tick(POLL_MS);
      expect(polls("c1")).toBe(afterFirstTick + 1);
      expect(result.current.stillAnswering).toBe(true);
      unmount();
    });

    it("when replying turns false it shows the server's messages, enables the composer and calls onTurnComplete", async () => {
      const onTurnComplete = vi.fn();
      const { result } = await loaded(
        "c1",
        conv("c1", [msg("user", "q", 0)], true),
        onTurnComplete,
      );
      serve(() =>
        conv("c1", [msg("user", "q", 0), msg("assistant", "whole reply", 9)]),
      );

      await tick(POLL_MS);
      expect(result.current.stillAnswering).toBe(false);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(transcript(result)).toEqual([
        ["user", "q"],
        ["assistant", "whole reply"],
      ]);
      expect(onTurnComplete).toHaveBeenCalledOnce();

      const settledPolls = polls("c1");
      await tick(POLL_MS * 3);
      expect(polls("c1")).toBe(settledPolls);
    });

    it("when replying turns false with the user's message last it shows the interruption line", async () => {
      const { result } = await loaded(
        "c1",
        conv("c1", [msg("user", "q", 0)], true),
      );
      serve(() => conv("c1", [msg("user", "q", 0)]));

      await tick(POLL_MS);
      expect(result.current.stillAnswering).toBe(false);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBe(INTERRUPTED);
      expect(transcript(result)).toEqual([["user", "q"]]);
    });

    it("loading a free conversation whose last message is the user's shows the interruption line and does not poll", async () => {
      const { result } = await loaded(
        "c1",
        conv("c1", [...EARLIER, msg("user", "unanswered", 9)]),
      );
      expect(result.current.error).toBe(INTERRUPTED);
      expect(result.current.stillAnswering).toBe(false);
      expect(result.current.isLoading).toBe(false);

      await tick(POLL_MS * 3);
      expect(polls("c1")).toBe(1);
    });

    it("loading a free conversation whose last message is the assistant's shows no error", async () => {
      const { result } = await loaded("c1", conv("c1", EARLIER));
      expect(result.current.error).toBeNull();
      expect(result.current.stillAnswering).toBe(false);
    });

    it("a failed poll is retried on the next tick without showing an error", async () => {
      const { result } = await loaded(
        "c1",
        conv("c1", [msg("user", "q", 0)], true),
      );
      serve(() => new Error("API 502: Bad Gateway"));

      await tick(POLL_MS);
      expect(polls("c1")).toBeGreaterThan(1);
      expect(result.current.error).toBeNull();
      expect(result.current.stillAnswering).toBe(true);

      serve(() =>
        conv("c1", [msg("user", "q", 0), msg("assistant", "whole reply", 9)]),
      );
      await tick(POLL_MS);
      expect(result.current.error).toBeNull();
      expect(result.current.stillAnswering).toBe(false);
      expect(transcript(result)).toEqual([
        ["user", "q"],
        ["assistant", "whole reply"],
      ]);
    });

    it("polling stops on unmount", async () => {
      const { unmount } = await loaded(
        "c1",
        conv("c1", [msg("user", "q", 0)], true),
      );
      await tick(POLL_MS);
      unmount();
      const before = polls("c1");

      await tick(POLL_MS * 5);
      expect(polls("c1")).toBe(before);
    });

    it("polling stops when the conversation changes", async () => {
      vi.useFakeTimers();
      serve((id) =>
        id === "c1"
          ? conv("c1", [msg("user", "q", 0)], true)
          : conv("c2", EARLIER),
      );
      const hook = renderHook(({ id }) => useChat(id, null), {
        initialProps: { id: "c1" },
      });
      await tick(0);
      expect(hook.result.current.stillAnswering).toBe(true);

      hook.rerender({ id: "c2" });
      await tick(0);
      const before = polls("c1");
      await tick(POLL_MS * 5);
      expect(polls("c1")).toBe(before);
      expect(hook.result.current.stillAnswering).toBe(false);
      expect(transcript(hook.result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
      ]);
      hook.unmount();
    });

    it("polling that never sees the reply end stops after 12 minutes with the taking-longer line and an enabled composer", async () => {
      const { result, unmount } = await loaded(
        "c1",
        conv("c1", [msg("user", "q", 0)], true),
      );

      await tick(11 * 60_000);
      expect(result.current.error).toBeNull();
      expect(result.current.stillAnswering).toBe(true);

      await tick(60_000 + POLL_MS);
      expect(result.current.error).toBe(TAKING_LONGER);
      expect(result.current.stillAnswering).toBe(false);
      expect(result.current.isLoading).toBe(false);

      const stopped = polls("c1");
      await tick(POLL_MS * 5);
      expect(polls("c1")).toBe(stopped);
      unmount();
    });
  });

  describe("after a lost connection", () => {
    it("on ConnectionLostError it drops the partial, clears the status, stays busy and polls the conversation", async () => {
      const onTurnComplete = vi.fn();
      const { result } = await loaded(
        "c1",
        conv("c1", EARLIER),
        onTurnComplete,
      );
      const turn = holdTurn();
      await start(result, "hi");
      act(() => {
        turn.handlers.onConversationId("c1");
        turn.handlers.onStatus?.("Searching your documents");
        turn.handlers.onChunk("partial");
      });
      serve(() => conv("c1", [...EARLIER, sent("hi", 10)], true));

      await lose(turn, new ConnectionLostError());
      expect(result.current.stillAnswering).toBe(true);
      expect(result.current.streamingContent).toBe("");
      expect(result.current.status).toBeNull();
      expect(result.current.isLoading).toBe(true);
      expect(result.current.error).toBeNull();
      expect(transcript(result)).not.toContainEqual(["assistant", "partial"]);

      const before = polls("c1");
      await tick(POLL_MS);
      expect(polls("c1")).toBeGreaterThan(before);
      expect(result.current.stillAnswering).toBe(true);

      serve(() =>
        conv("c1", [
          ...EARLIER,
          sent("hi", 10),
          msg("assistant", "whole reply", 20),
        ]),
      );
      await tick(POLL_MS);
      expect(result.current.stillAnswering).toBe(false);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
        ["assistant", "whole reply"],
      ]);
      expect(onTurnComplete).toHaveBeenCalledOnce();
    });

    it("a lost connection whose reply never lands shows the interruption line and still calls onTurnComplete", async () => {
      const onTurnComplete = vi.fn();
      const { result } = await loaded(
        "c1",
        conv("c1", EARLIER),
        onTurnComplete,
      );
      const turn = holdTurn();
      await start(result, "hi");
      act(() => turn.handlers.onConversationId("c1"));
      serve(() => conv("c1", [...EARLIER, sent("hi", 10)]));

      await lose(turn, new ConnectionLostError());
      await tick(POLL_MS);
      expect(result.current.error).toBe(INTERRUPTED);
      expect(result.current.stillAnswering).toBe(false);
      expect(result.current.isLoading).toBe(false);
      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
      ]);
      expect(onTurnComplete).toHaveBeenCalledOnce();
    });

    it("a first turn that loses its connection after the prelude polls the id the prelude gave", async () => {
      vi.useFakeTimers();
      const onTurnComplete = vi.fn();
      const hook = renderHook(() =>
        useChat(null, null, undefined, onTurnComplete),
      );
      const turn = holdTurn();
      await start(hook.result, "hi");
      act(() => {
        turn.handlers.onConversationId("new-1");
        turn.handlers.onChunk("partial");
      });
      serve(() => conv("new-1", [sent("hi", 10)], true));

      await lose(turn, new ConnectionLostError());
      expect(hook.result.current.stillAnswering).toBe(true);
      await tick(POLL_MS);
      expect(polls("new-1")).toBeGreaterThan(0);
      expect(getConversation.mock.calls.every(([id]) => id === "new-1")).toBe(
        true,
      );

      serve(() =>
        conv("new-1", [sent("hi", 10), msg("assistant", "whole reply", 20)]),
      );
      await tick(POLL_MS);
      expect(hook.result.current.stillAnswering).toBe(false);
      expect(transcript(hook.result)).toEqual([
        ["user", "hi"],
        ["assistant", "whole reply"],
      ]);
      expect(onTurnComplete).toHaveBeenCalledOnce();
    });

    it("a first turn that loses its connection before the prelude shows the interruption line and calls onTurnComplete without polling", async () => {
      vi.useFakeTimers();
      const onTurnComplete = vi.fn();
      const hook = renderHook(() =>
        useChat(null, null, undefined, onTurnComplete),
      );
      const turn = holdTurn();
      await start(hook.result, "hi");

      await lose(turn, new ConnectionLostError());
      expect(hook.result.current.error).toBe(INTERRUPTED);
      expect(hook.result.current.stillAnswering).toBe(false);
      expect(hook.result.current.isLoading).toBe(false);
      expect(onTurnComplete).toHaveBeenCalledOnce();

      await tick(POLL_MS * 3);
      expect(getConversation).not.toHaveBeenCalled();
    });

    it("a lost connection before the prelude on an existing conversation polls that conversation", async () => {
      const onTurnComplete = vi.fn();
      const { result } = await loaded(
        "c1",
        conv("c1", EARLIER),
        onTurnComplete,
      );
      const turn = holdTurn();
      await start(result, "hi");
      serve(() =>
        conv("c1", [
          ...EARLIER,
          sent("hi", 10),
          msg("assistant", "whole reply", 20),
        ]),
      );

      await lose(turn, new ConnectionLostError());
      await tick(POLL_MS);
      expect(polls("c1")).toBeGreaterThan(1);
      expect(result.current.stillAnswering).toBe(false);
      expect(result.current.error).toBeNull();
      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
        ["assistant", "whole reply"],
      ]);
      expect(onTurnComplete).toHaveBeenCalledOnce();
    });
  });

  describe("a send rejected before any response", () => {
    const OFFLINE = () => new TypeError("Failed to fetch");

    it("sends a fresh UUID as the message id with every send", async () => {
      const { result } = await loaded("c1", conv("c1", EARLIER));
      const first = holdTurn();
      const { settled: one } = await start(result, "hi");
      await settle(one, () => first.end());
      const second = holdTurn();
      const { settled: two } = await start(result, "hi");
      await settle(two, () => second.end());

      const ids = streamChat.mock.calls.map((call) => call[4]);
      expect(ids).toHaveLength(2);
      for (const id of ids) {
        expect(id).toMatch(
          /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
        );
      }
      expect(ids[0]).not.toBe(ids[1]);
    });

    it("shows Still answering while it checks, then after two reads without its id the not-sent line, removes the message and returns the draft", async () => {
      const onTurnComplete = vi.fn();
      const { result } = await loaded(
        "c1",
        conv("c1", EARLIER),
        onTurnComplete,
      );
      const check = deferred<ConversationDetail>();
      serve(() => check.promise);
      const turn = holdTurn();
      await start(result, "hi");

      await lose(turn, OFFLINE());
      expect(result.current.stillAnswering).toBe(true);
      expect(result.current.error).toBeNull();

      await tick(POLL_MS);
      await act(async () => {
        check.resolve(conv("c1", EARLIER));
        await vi.advanceTimersByTimeAsync(0);
      });
      // One negative read is not final.
      expect(result.current.stillAnswering).toBe(true);
      expect(result.current.error).toBeNull();
      expect(result.current.restoreDraft).toBeNull();

      await tick(POLL_MS);
      expect(result.current.error).toBe(NOT_SENT);
      expect(result.current.restoreDraft).toBe("hi");
      expect(result.current.stillAnswering).toBe(false);
      expect(result.current.isLoading).toBe(false);
      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
      ]);
      expect(onTurnComplete).not.toHaveBeenCalled();
    });

    it("a send whose id is on the server counts as arrived: it shows the server's messages and calls onTurnComplete", async () => {
      const onTurnComplete = vi.fn();
      const { result } = await loaded(
        "c1",
        conv("c1", EARLIER),
        onTurnComplete,
      );
      const turn = holdTurn();
      await start(result, "hi");
      serve(() =>
        conv("c1", [
          ...EARLIER,
          sent("hi", 10),
          msg("assistant", "whole reply", 20),
        ]),
      );

      await lose(turn, OFFLINE());
      await tick(POLL_MS);
      expect(result.current.error).toBeNull();
      expect(result.current.restoreDraft).toBeNull();
      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
        ["assistant", "whole reply"],
      ]);
      expect(onTurnComplete).toHaveBeenCalledOnce();
    });

    it("a request aborted before any response (the silence limit) shows Still answering without an error and polls like an offline send", async () => {
      const onTurnComplete = vi.fn();
      const { result } = await loaded(
        "c1",
        conv("c1", EARLIER),
        onTurnComplete,
      );
      const turn = holdTurn();
      await start(result, "hi");
      const before = polls("c1");

      await lose(
        turn,
        new DOMException("The operation was aborted.", "AbortError"),
      );
      expect(result.current.stillAnswering).toBe(true);
      expect(result.current.isLoading).toBe(true);
      expect(result.current.error).toBeNull();

      serve(() =>
        conv("c1", [
          ...EARLIER,
          sent("hi", 10),
          msg("assistant", "whole reply", 20),
        ]),
      );
      await tick(POLL_MS);
      expect(polls("c1")).toBeGreaterThan(before);
      expect(result.current.error).toBeNull();
      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
        ["assistant", "whole reply"],
      ]);
      expect(onTurnComplete).toHaveBeenCalledOnce();
    });

    it("an id absent on the first read and present on the second counts as arrived", async () => {
      const onTurnComplete = vi.fn();
      const { result } = await loaded(
        "c1",
        conv("c1", EARLIER),
        onTurnComplete,
      );
      const turn = holdTurn();
      await start(result, "hi");
      serve(() => conv("c1", EARLIER));

      await lose(turn, OFFLINE());
      await tick(POLL_MS);
      expect(result.current.stillAnswering).toBe(true);

      serve(() =>
        conv("c1", [
          ...EARLIER,
          sent("hi", 10),
          msg("assistant", "whole reply", 20),
        ]),
      );
      await tick(POLL_MS);
      expect(result.current.error).toBeNull();
      expect(result.current.restoreDraft).toBeNull();
      expect(result.current.stillAnswering).toBe(false);
      expect(transcript(result)).toContainEqual(["assistant", "whole reply"]);
      expect(onTurnComplete).toHaveBeenCalledOnce();
    });

    it("a read that is replying between two reads without the id restarts the count", async () => {
      const { result } = await loaded("c1", conv("c1", EARLIER));
      const turn = holdTurn();
      await start(result, "hi");
      serve(() => conv("c1", EARLIER));

      await lose(turn, OFFLINE());
      await tick(POLL_MS);
      serve(() => conv("c1", EARLIER, true));
      await tick(POLL_MS);
      serve(() => conv("c1", EARLIER));
      await tick(POLL_MS);
      expect(result.current.stillAnswering).toBe(true);
      expect(result.current.error).toBeNull();

      await tick(POLL_MS);
      expect(result.current.error).toBe(NOT_SENT);
    });

    it("shows the not-sent line and returns the draft when the conversation's first load had failed", async () => {
      const { result } = await loaded("c1", new Error("API 500: Server Error"));
      const turn = holdTurn();
      await start(result, "hi");
      serve(() => conv("c1", EARLIER));

      await lose(turn, OFFLINE());
      await tick(POLL_MS * 2);
      expect(result.current.error).toBe(NOT_SENT);
      expect(result.current.restoreDraft).toBe("hi");
      expect(result.current.isLoading).toBe(false);
      expect(transcript(result)).not.toContainEqual(["user", "hi"]);
    });

    it("a lost repeat of an earlier identical text is reported as not sent", async () => {
      const before = [msg("user", "hi", 0), msg("assistant", "answer", 5)];
      const { result } = await loaded("c1", conv("c1", before));
      const turn = holdTurn();
      await start(result, "hi");
      serve(() => conv("c1", before));

      await lose(turn, OFFLINE());
      await tick(POLL_MS * 2);
      expect(result.current.error).toBe(NOT_SENT);
      expect(result.current.restoreDraft).toBe("hi");
      expect(transcript(result)).toEqual([
        ["user", "hi"],
        ["assistant", "answer"],
      ]);
    });

    it("on a new chat with no id it is an error as before, without polling", async () => {
      vi.useFakeTimers();
      const hook = renderHook(() => useChat(null, null));
      const turn = holdTurn();
      await start(hook.result, "hi");

      await lose(turn, OFFLINE());
      expect(hook.result.current.error).not.toBeNull();
      expect(hook.result.current.stillAnswering).toBe(false);
      expect(hook.result.current.isLoading).toBe(false);
      await tick(POLL_MS * 3);
      expect(getConversation).not.toHaveBeenCalled();
    });
  });

  describe("after Stop", () => {
    const fetchMock = vi.fn<typeof fetch>();

    beforeEach(() => {
      vi.stubGlobal("fetch", fetchMock);
      fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    });

    afterEach(() => {
      fetchMock.mockReset();
      vi.unstubAllGlobals();
    });

    async function pressStop(result: { current: ReturnType<typeof useChat> }) {
      await act(async () => {
        await result.current.stop();
      });
    }

    it("a stopped reply whose stream is lost settles with the user's message last and no error line", async () => {
      const { result } = await loaded("c1", conv("c1", EARLIER));
      const turn = holdTurn();
      await start(result, "hi");
      act(() => turn.handlers.onConversationId("c1"));
      await pressStop(result);
      serve(() => conv("c1", [...EARLIER, sent("hi", 10)], true));

      await lose(turn, new ConnectionLostError());
      expect(result.current.stillAnswering).toBe(true);

      serve(() => conv("c1", [...EARLIER, sent("hi", 10)]));
      await tick(POLL_MS);
      expect(result.current.stillAnswering).toBe(false);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
      ]);
    });

    it("a load that lands after a stopped reply ended polls to the user's message last with no error line", async () => {
      vi.useFakeTimers();
      const load = deferred<ConversationDetail>();
      serve(() => load.promise);
      const hook = renderHook(() => useChat("c1", null));
      const turn = holdTurn();
      const { settled } = await start(hook.result, "hi");
      act(() => turn.handlers.onConversationId("c1"));
      await pressStop(hook.result);
      await settle(settled, () =>
        turn.fail(new ReplyFailedError("reply_failed")),
      );
      expect(hook.result.current.error).toBeNull();

      // Read before the stop took effect: still replying.
      await act(async () => {
        load.resolve(conv("c1", [...EARLIER, msg("user", "hi", 10)], true));
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(hook.result.current.stillAnswering).toBe(true);

      serve(() => conv("c1", [...EARLIER, msg("user", "hi", 10)]));
      await tick(POLL_MS);
      expect(hook.result.current.stillAnswering).toBe(false);
      expect(hook.result.current.error).toBeNull();
      expect(transcript(hook.result).at(-1)).toEqual(["user", "hi"]);
    });
  });

  describe("a load landing mid-send", () => {
    it("does not show Still answering, and the send's own stream decides", async () => {
      vi.useFakeTimers();
      const load = deferred<ConversationDetail>();
      serve(() => load.promise);
      const hook = renderHook(() => useChat("c1", null));
      const turn = holdTurn();
      await start(hook.result, "hi");
      act(() => turn.handlers.onConversationId("c1"));

      await act(async () => {
        load.resolve(conv("c1", [...EARLIER, msg("user", "hi", 10)], true));
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(hook.result.current.stillAnswering).toBe(false);
      expect(hook.result.current.error).toBeNull();

      act(() => turn.handlers.onChunk("Hello"));
      expect(hook.result.current.streamingContent).toBe("Hello");
      await act(async () => {
        turn.end();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(hook.result.current.isLoading).toBe(false);
      expect(hook.result.current.stillAnswering).toBe(false);
      expect(transcript(hook.result).at(-1)).toEqual(["assistant", "Hello"]);

      await tick(POLL_MS * 3);
      expect(polls("c1")).toBe(1);
    });

    it("does not show the interruption line while the send is in flight", async () => {
      vi.useFakeTimers();
      const load = deferred<ConversationDetail>();
      serve(() => load.promise);
      const hook = renderHook(() => useChat("c1", null));
      const turn = holdTurn();
      await start(hook.result, "hi");

      await act(async () => {
        load.resolve(conv("c1", [...EARLIER, msg("user", "hi", 10)]));
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(hook.result.current.error).toBeNull();
      expect(hook.result.current.isLoading).toBe(true);

      await act(async () => {
        turn.handlers.onChunk("Hello");
        turn.end();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(hook.result.current.error).toBeNull();
    });
  });
});

describe("useChat stop", () => {
  const INTERRUPTED = "The reply was interrupted.";
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  function transcript(result: { current: ReturnType<typeof useChat> }) {
    return result.current.messages.map((m) => [m.role, m.content]);
  }

  function stopAnswers(status: number) {
    fetchMock.mockResolvedValue(new Response(null, { status }));
  }

  // The next stop request stays in flight until the test answers it.
  function stopHeld(): { answer: (status: number) => void } {
    const held = {} as { answer: (status: number) => void };
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          held.answer = (status) => resolve(new Response(null, { status }));
        }),
    );
    return held;
  }

  // A reply in a new chat whose prelude (the conversation id) has arrived.
  async function replying(turn: Turn) {
    const hook = renderHook(() => useChat(null, null));
    const { settled } = await start(hook.result, "hi");
    act(() => turn.handlers.onConversationId("c1"));
    return { result: hook.result, settled };
  }

  // Returns the stop's promise wrapped, so awaiting the press does not also
  // await the stop request.
  async function pressStop(result: {
    current: ReturnType<typeof useChat>;
  }): Promise<{ stopping: Promise<void> }> {
    let stopping!: Promise<void>;
    await act(async () => {
      stopping = Promise.resolve(result.current.stop());
      // A rejection is asserted through the hook's state, not here.
      stopping.catch(() => {});
    });
    return { stopping };
  }

  it("Stop is not offered before the reply's prelude arrives, and is once it has", async () => {
    const turn = holdTurn();
    const hook = renderHook(() => useChat(null, null));
    await start(hook.result, "hi");
    expect(hook.result.current.canStop).toBe(false);

    act(() => turn.handlers.onConversationId("c1"));
    expect(hook.result.current.canStop).toBe(true);
  });

  it("Stop asks the server to stop the reply's conversation", async () => {
    const turn = holdTurn();
    stopAnswers(204);
    const { result } = await replying(turn);

    await act(async () => {
      await result.current.stop();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [input, init] = fetchMock.mock.calls[0];
    expect(String(input)).toBe("/api/conversations/c1/stop");
    expect((init?.method ?? "GET").toUpperCase()).toBe("POST");
  });

  it("a stop in flight takes Stop away at once, so it cannot be pressed twice", async () => {
    const turn = holdTurn();
    stopHeld();
    const { result } = await replying(turn);

    await pressStop(result);

    expect(result.current.canStop).toBe(false);
    expect(result.current.isLoading).toBe(true);
  });

  it("a stopped reply that ends with [DONE] keeps the partial as the assistant message, with no error line", async () => {
    const turn = holdTurn();
    stopAnswers(204);
    const { result, settled } = await replying(turn);
    act(() => {
      turn.handlers.onChunk("Half an ");
      turn.handlers.onChunk("answer");
    });
    const { stopping } = await pressStop(result);

    await act(async () => {
      await stopping;
    });
    await settle(settled, () => turn.end());

    expect(transcript(result)).toEqual([
      ["user", "hi"],
      ["assistant", "Half an answer"],
    ]);
    expect(result.current.error).toBeNull();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.canStop).toBe(false);
  });

  it("the composer stays busy until the stop request settles, even when [DONE] arrives first", async () => {
    const turn = holdTurn();
    const held = stopHeld();
    const { result, settled } = await replying(turn);
    act(() => turn.handlers.onChunk("Half an answer"));
    const { stopping } = await pressStop(result);

    await settle(settled, () => turn.end());
    expect(transcript(result)).toEqual([
      ["user", "hi"],
      ["assistant", "Half an answer"],
    ]);
    expect(result.current.isLoading).toBe(true);

    await act(async () => {
      held.answer(204);
      await stopping;
    });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("after stop, a following reply_failed shows no error line and keeps the user message last", async () => {
    const turn = holdTurn();
    stopAnswers(204);
    const { result, settled } = await replying(turn);
    const { stopping } = await pressStop(result);
    await act(async () => {
      await stopping;
    });

    await settle(settled, () =>
      turn.fail(new ReplyFailedError("reply_failed")),
    );

    expect(result.current.error).toBeNull();
    expect(transcript(result)).toEqual([["user", "hi"]]);
    expect(result.current.isLoading).toBe(false);
  });

  it("a reply_failed that arrives before the stop request's 204 shows no error line", async () => {
    const turn = holdTurn();
    const held = stopHeld();
    const { result, settled } = await replying(turn);
    const { stopping } = await pressStop(result);

    await settle(settled, () =>
      turn.fail(new ReplyFailedError("reply_failed")),
    );
    expect(result.current.isLoading).toBe(true);
    await act(async () => {
      held.answer(204);
      await stopping;
    });

    expect(result.current.error).toBeNull();
    expect(transcript(result)).toEqual([["user", "hi"]]);
    expect(result.current.isLoading).toBe(false);
  });

  it("a stop request that fails with an HTTP status offers Stop again and a later reply failure still shows", async () => {
    const turn = holdTurn();
    stopAnswers(500);
    const { result, settled } = await replying(turn);
    const { stopping } = await pressStop(result);
    await act(async () => {
      await stopping.catch(() => {});
    });

    expect(result.current.canStop).toBe(true);
    expect(result.current.isLoading).toBe(true);
    expect(result.current.error).toBeNull();

    await settle(settled, () =>
      turn.fail(new ReplyFailedError("reply_failed")),
    );
    expect(result.current.error).toBe(INTERRUPTED);
  });

  it("a stop request that fails with a 404 offers Stop again and shows no error line", async () => {
    const turn = holdTurn();
    stopAnswers(404);
    const { result } = await replying(turn);
    const { stopping } = await pressStop(result);
    await act(async () => {
      await stopping.catch(() => {});
    });

    expect(result.current.canStop).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("a stop request that fails on the network offers Stop again, and a later reply failure shows no error line", async () => {
    const turn = holdTurn();
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const { result, settled } = await replying(turn);
    const { stopping } = await pressStop(result);
    await act(async () => {
      await stopping.catch(() => {});
    });

    expect(result.current.canStop).toBe(true);
    expect(result.current.error).toBeNull();

    await settle(settled, () =>
      turn.fail(new ReplyFailedError("reply_failed")),
    );
    expect(result.current.error).toBeNull();
    expect(transcript(result)).toEqual([["user", "hi"]]);
  });

  it("a stop request that never settles frees the composer after its 10 s timeout", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    // The request's own bound, driven by the fake clock.
    vi.spyOn(AbortSignal, "timeout").mockImplementation((ms: number) => {
      const controller = new AbortController();
      setTimeout(
        () => controller.abort(new DOMException("timed out", "TimeoutError")),
        ms,
      );
      return controller.signal;
    });
    fetchMock.mockImplementation(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(init.signal!.reason),
          );
        }),
    );
    const turn = holdTurn();
    const { result, settled } = await replying(turn);
    act(() => turn.handlers.onChunk("Half an answer"));
    await pressStop(result);
    await settle(settled, () => turn.end());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9_000);
    });
    expect(result.current.isLoading).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(transcript(result)).toEqual([
      ["user", "hi"],
      ["assistant", "Half an answer"],
    ]);
  });

  it("a stop request that times out keeps the stop: a reply_failed after it shows no error line", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    vi.spyOn(AbortSignal, "timeout").mockImplementation((ms: number) => {
      const controller = new AbortController();
      setTimeout(
        () => controller.abort(new DOMException("timed out", "TimeoutError")),
        ms,
      );
      return controller.signal;
    });
    fetchMock.mockImplementation(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(init.signal!.reason),
          );
        }),
    );
    const turn = holdTurn();
    const { result, settled } = await replying(turn);
    await pressStop(result);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_500);
    });
    expect(result.current.canStop).toBe(true);

    await settle(settled, () =>
      turn.fail(new ReplyFailedError("reply_failed")),
    );
    expect(result.current.error).toBeNull();
    expect(transcript(result)).toEqual([["user", "hi"]]);
  });

  it("no send goes out while the stop request is still in flight", async () => {
    const turn = holdTurn();
    const held = stopHeld();
    const { result, settled } = await replying(turn);
    const { stopping } = await pressStop(result);
    await settle(settled, () => turn.end());

    await act(async () => {
      await result.current.send("too soon");
    });
    expect(streamChat).toHaveBeenCalledTimes(1);

    await act(async () => {
      held.answer(204);
      await stopping;
    });
  });

  it("the next send after a stopped reply shows a reply failure again", async () => {
    const first = holdTurn();
    stopAnswers(204);
    const { result, settled } = await replying(first);
    const { stopping } = await pressStop(result);
    await act(async () => {
      await stopping;
    });
    await settle(settled, () =>
      first.fail(new ReplyFailedError("reply_failed")),
    );
    expect(result.current.error).toBeNull();

    const second = holdTurn();
    const next = await start(result, "again");
    await settle(next.settled, () =>
      second.fail(new ReplyFailedError("reply_failed")),
    );

    expect(result.current.error).toBe(INTERRUPTED);
  });
});

describe("useChat try again", () => {
  const INTERRUPTED = "The reply was interrupted.";
  const POLL_MS = 2_000;
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.useFakeTimers();
    // stopReply's request: a 204 unless a test holds or fails it.
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  type Message = ConversationDetail["messages"][number];

  function msg(
    role: "user" | "assistant",
    content: string,
    id: string,
  ): Message {
    return {
      id,
      role,
      content,
      created_at: "2026-10-01T10:00:00Z",
      sources: null,
    };
  }

  function conv(messages: Message[], replying = false): ConversationDetail {
    return { ...detail("c1", messages), replying };
  }

  const EARLIER = [
    msg("user", "earlier", "u0"),
    msg("assistant", "answer", "a0"),
  ];

  function serve(answer: () => ConversationDetail | Error) {
    getConversation.mockImplementation(async () => {
      const a = answer();
      if (a instanceof Error) throw a;
      return a;
    });
  }

  async function tick(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  function transcript(result: { current: ReturnType<typeof useChat> }) {
    return result.current.messages.map((m) => [m.role, m.content]);
  }

  // The id the hook chose for its latest send, as streamChat received it.
  function sentId(): string {
    const id = streamChat.mock.calls.at(-1)?.[4];
    if (!id) throw new Error("no message id was sent");
    return id;
  }

  type Retry = {
    handlers: StreamHandlers;
    end: () => void;
    fail: (reason: unknown) => void;
  };

  // The next streamRetry call stays in flight until the test ends or fails it.
  function holdRetry(): Retry {
    const retry = {} as Retry;
    streamRetry.mockImplementationOnce(
      (_conversationId, _after, _replace, handlers) =>
        new Promise<void>((resolve, reject) => {
          retry.handlers = handlers;
          retry.end = () => resolve();
          retry.fail = reject;
        }),
    );
    return retry;
  }

  // The retry's own promise is never awaited: on some outcomes it settles
  // only after polling.
  async function pressRetry(result: { current: ReturnType<typeof useChat> }) {
    await act(async () => {
      Promise.resolve(result.current.retry()).catch(() => {});
      await vi.advanceTimersByTimeAsync(0);
    });
  }

  async function finish(fn: () => void) {
    await act(async () => {
      fn();
      await vi.advanceTimersByTimeAsync(0);
    });
  }

  type Callbacks = {
    onConversationCreated?: (id: string) => void;
    onTurnComplete?: () => void;
    onTurnStarted?: () => void;
  };

  async function loaded(
    first: ConversationDetail | Error,
    model: string | null = null,
    callbacks: Callbacks = {},
  ) {
    serve(() => first);
    const hook = renderHook(() =>
      useChat(
        "c1",
        model,
        callbacks.onConversationCreated,
        callbacks.onTurnComplete,
        callbacks.onTurnStarted,
      ),
    );
    await tick(0);
    return hook;
  }

  // A loaded conversation whose last message is the user's: the interrupted
  // line.
  async function interrupted(
    model: string | null = null,
    callbacks: Callbacks = {},
  ) {
    const hook = await loaded(conv([msg("user", "q", "u1")]), model, callbacks);
    expect(hook.result.current.error).toBe(INTERRUPTED);
    return hook;
  }

  // A send in a loaded conversation whose reply is stopped after `kept` was
  // written (nothing when empty), the stop answered 204 and the stream ended
  // with [DONE].
  async function stopped(kept: string) {
    const hook = await loaded(conv(EARLIER));
    const turn = holdTurn();
    const { settled } = await start(hook.result, "hi");
    act(() => {
      turn.handlers.onConversationId("c1");
      if (kept) turn.handlers.onChunk(kept);
    });
    await act(async () => {
      await hook.result.current.stop();
    });
    await act(async () => {
      turn.end();
      await settled;
    });
    return hook;
  }

  describe("canRetry", () => {
    it("is true on the interrupted line of a loaded conversation whose last message is the user's", async () => {
      const { result } = await interrupted();
      expect(result.current.canRetry).toBe(true);
    });

    it("is false when the conversation loads with a reply last", async () => {
      const { result } = await loaded(conv(EARLIER));
      expect(result.current.error).toBeNull();
      expect(result.current.canRetry).toBe(false);
    });

    it("is false on a failed load", async () => {
      const { result } = await loaded(new Error("boom"));
      expect(result.current.error).not.toBeNull();
      expect(result.current.error).not.toBe(INTERRUPTED);
      expect(result.current.canRetry).toBe(false);
    });

    it("is true after a reply failure once the prelude gave the conversation an id", async () => {
      const turn = holdTurn();
      const { result } = renderHook(() => useChat(null, null));
      const { settled } = await start(result, "hi");
      act(() => {
        turn.handlers.onConversationId("c9");
        turn.handlers.onChunk("Failing");
      });
      await act(async () => {
        turn.fail(new ReplyFailedError("reply_failed"));
        await settled.catch(() => {});
      });
      expect(result.current.error).toBe(INTERRUPTED);
      expect(result.current.canRetry).toBe(true);
    });

    it("is false for a first turn cut before its prelude: no conversation id yet", async () => {
      const turn = holdTurn();
      const { result } = renderHook(() => useChat(null, null));
      const { settled } = await start(result, "hi");
      await act(async () => {
        turn.fail(new ReplyFailedError("reply_failed"));
        await settled.catch(() => {});
      });
      expect(result.current.canRetry).toBe(false);
    });

    it("is false on a reply already in progress", async () => {
      const { result } = await loaded(conv(EARLIER));
      streamChat.mockRejectedValueOnce(
        new TurnInProgressError(
          "A reply is already in progress in this conversation.",
        ),
      );
      await start(result, "hi");
      await tick(0);
      expect(result.current.error).not.toBe(INTERRUPTED);
      expect(result.current.canRetry).toBe(false);
    });

    it("is false while a retry runs", async () => {
      const { result } = await interrupted();
      holdRetry();
      await pressRetry(result);
      expect(result.current.isLoading).toBe(true);
      expect(result.current.canRetry).toBe(false);
    });
  });

  describe("after a failed reply", () => {
    it("retry asks the server to rewrite the reply to the last user message, with the composer's model and replace false", async () => {
      const { result } = await interrupted("claude-sonnet");
      holdRetry();
      await pressRetry(result);
      expect(streamRetry).toHaveBeenCalledTimes(1);
      const [conversationId, after, replace, , model] =
        streamRetry.mock.calls[0];
      expect(conversationId).toBe("c1");
      expect(after).toBe("u1");
      expect(replace).toBe(false);
      expect(model).toBe("claude-sonnet");
      expect(streamChat).not.toHaveBeenCalled();
    });

    it("retry clears the interrupted line at once, adds no user message, and streams the reply into the thread", async () => {
      const { result } = await interrupted();
      const retry = holdRetry();
      await pressRetry(result);
      expect(result.current.error).toBeNull();
      expect(transcript(result)).toEqual([["user", "q"]]);

      act(() => {
        retry.handlers.onConversationId("c1");
        retry.handlers.onStatus?.("Searching your documents");
      });
      expect(result.current.status).toBe("Searching your documents");
      act(() => retry.handlers.onChunk("Recovered"));
      expect(result.current.streamingContent).toBe("Recovered");
      expect(transcript(result)).toEqual([["user", "q"]]);
    });

    it("Stop is offered during a retry once its prelude has arrived", async () => {
      const { result } = await interrupted();
      const retry = holdRetry();
      await pressRetry(result);
      expect(result.current.canStop).toBe(false);
      act(() => retry.handlers.onConversationId("c1"));
      expect(result.current.canStop).toBe(true);
    });

    it("a successful retry shows the conversation as the server holds it after [DONE] and calls onTurnComplete once, never onConversationCreated or onTurnStarted", async () => {
      const onConversationCreated = vi.fn();
      const onTurnComplete = vi.fn();
      const onTurnStarted = vi.fn();
      const { result } = await interrupted(null, {
        onConversationCreated,
        onTurnComplete,
        onTurnStarted,
      });
      const retry = holdRetry();
      await pressRetry(result);
      act(() => {
        retry.handlers.onConversationId("c1");
        retry.handlers.onChunk("Recovered reply.");
      });
      const readsBefore = getConversation.mock.calls.length;
      serve(() =>
        conv([
          msg("user", "q", "u1"),
          msg("assistant", "Recovered reply.", "a1"),
        ]),
      );
      await finish(() => retry.end());

      expect(getConversation.mock.calls.length).toBeGreaterThan(readsBefore);
      expect(transcript(result)).toEqual([
        ["user", "q"],
        ["assistant", "Recovered reply."],
      ]);
      expect(result.current.error).toBeNull();
      expect(result.current.isLoading).toBe(false);
      expect(result.current.streamingContent).toBe("");
      expect(result.current.canRetry).toBe(false);
      expect(onTurnComplete).toHaveBeenCalledTimes(1);
      expect(onConversationCreated).not.toHaveBeenCalled();
      expect(onTurnStarted).not.toHaveBeenCalled();
    });

    it("a successful retry whose re-read after [DONE] fails keeps the streamed reply shown", async () => {
      const { result } = await interrupted();
      const retry = holdRetry();
      await pressRetry(result);
      act(() => {
        retry.handlers.onConversationId("c1");
        retry.handlers.onChunk("Recovered reply.");
      });
      serve(() => new Error("boom"));
      await finish(() => retry.end());

      expect(transcript(result)).toEqual([
        ["user", "q"],
        ["assistant", "Recovered reply."],
      ]);
      expect(result.current.isLoading).toBe(false);
    });

    it("a retry that fails again shows the interrupted line with Try again and keeps the question last", async () => {
      const onTurnComplete = vi.fn();
      const { result } = await interrupted(null, { onTurnComplete });
      const retry = holdRetry();
      await pressRetry(result);
      act(() => {
        retry.handlers.onConversationId("c1");
        retry.handlers.onChunk("Failing reply");
      });
      await finish(() => retry.fail(new ReplyFailedError("reply_failed")));

      expect(result.current.error).toBe(INTERRUPTED);
      expect(result.current.canRetry).toBe(true);
      expect(transcript(result)).toEqual([["user", "q"]]);
      expect(result.current.streamingContent).toBe("");
      expect(result.current.isLoading).toBe(false);
      expect(onTurnComplete).not.toHaveBeenCalled();
    });

    it("no retry is sent while a send is in flight", async () => {
      const { result } = await interrupted();
      holdTurn();
      await start(result, "again");
      await pressRetry(result);
      expect(streamRetry).not.toHaveBeenCalled();
    });
  });

  describe("refusals and lost retries", () => {
    it("NothingToRetryError re-reads the conversation and shows it with no line", async () => {
      const { result } = await interrupted();
      streamRetry.mockRejectedValueOnce(new NothingToRetryError());
      serve(() =>
        conv([
          msg("user", "q", "u1"),
          msg("assistant", "Other tab's reply.", "a1"),
        ]),
      );
      await pressRetry(result);
      await tick(0);

      expect(transcript(result)).toEqual([
        ["user", "q"],
        ["assistant", "Other tab's reply."],
      ]);
      expect(result.current.error).toBeNull();
      expect(result.current.canRetry).toBe(false);
      expect(result.current.isLoading).toBe(false);
    });

    it("NothingToRetryError whose re-read still ends with the user's message shows the interrupted line with Try again", async () => {
      const { result } = await interrupted();
      streamRetry.mockRejectedValueOnce(new NothingToRetryError());
      await pressRetry(result);
      await tick(0);

      expect(transcript(result)).toEqual([["user", "q"]]);
      expect(result.current.error).toBe(INTERRUPTED);
      expect(result.current.canRetry).toBe(true);
    });

    it("NothingToRetryError whose re-read finds a reply running shows Still answering and polls until it lands", async () => {
      const { result } = await interrupted();
      streamRetry.mockRejectedValueOnce(new NothingToRetryError());
      serve(() => conv([msg("user", "q", "u1")], true));
      await pressRetry(result);
      await tick(0);
      expect(result.current.stillAnswering).toBe(true);
      expect(result.current.error).toBeNull();

      serve(() =>
        conv([msg("user", "q", "u1"), msg("assistant", "Landed.", "a1")]),
      );
      await tick(POLL_MS);
      await tick(POLL_MS);
      expect(result.current.stillAnswering).toBe(false);
      expect(transcript(result)).toEqual([
        ["user", "q"],
        ["assistant", "Landed."],
      ]);
      expect(result.current.error).toBeNull();
    });

    it("AlreadyAnsweredError re-reads the conversation and shows the answer with no line", async () => {
      const { result } = await interrupted();
      streamRetry.mockRejectedValueOnce(new AlreadyAnsweredError());
      serve(() =>
        conv([
          msg("user", "q", "u1"),
          msg("assistant", "Other tab's reply.", "a1"),
        ]),
      );
      await pressRetry(result);
      await tick(0);

      expect(transcript(result)).toEqual([
        ["user", "q"],
        ["assistant", "Other tab's reply."],
      ]);
      expect(result.current.error).toBeNull();
      expect(result.current.canRetry).toBe(false);
    });

    it("a retry refused because a reply is in progress shows Still answering and polls until that reply lands", async () => {
      const { result } = await interrupted();
      streamRetry.mockRejectedValueOnce(
        new TurnInProgressError(
          "A reply is already in progress in this conversation.",
        ),
      );
      serve(() => conv([msg("user", "q", "u1")], true));
      await pressRetry(result);
      await tick(0);
      expect(result.current.stillAnswering).toBe(true);
      expect(result.current.error).toBeNull();

      serve(() =>
        conv([
          msg("user", "q", "u1"),
          msg("assistant", "Other tab's reply.", "a1"),
        ]),
      );
      await tick(POLL_MS);
      await tick(POLL_MS);
      expect(result.current.stillAnswering).toBe(false);
      expect(transcript(result)).toEqual([
        ["user", "q"],
        ["assistant", "Other tab's reply."],
      ]);
      expect(result.current.error).toBeNull();
    });

    it("a retry whose stream is lost polls and shows the reply the server saved", async () => {
      const { result } = await interrupted();
      const retry = holdRetry();
      await pressRetry(result);
      act(() => {
        retry.handlers.onConversationId("c1");
        retry.handlers.onChunk("Recov");
      });
      serve(() => conv([msg("user", "q", "u1")], true));
      await finish(() => retry.fail(new ConnectionLostError()));
      expect(result.current.stillAnswering).toBe(true);

      serve(() =>
        conv([
          msg("user", "q", "u1"),
          msg("assistant", "Recovered reply.", "a1"),
        ]),
      );
      await tick(POLL_MS);
      await tick(POLL_MS);
      expect(result.current.stillAnswering).toBe(false);
      expect(transcript(result)).toEqual([
        ["user", "q"],
        ["assistant", "Recovered reply."],
      ]);
      expect(result.current.error).toBeNull();
    });

    it("a retry lost to a network failure with no response decides interrupted only after two consecutive free reads", async () => {
      const { result } = await interrupted();
      const readsBefore = getConversation.mock.calls.length;
      streamRetry.mockRejectedValueOnce(new TypeError("Failed to fetch"));
      await pressRetry(result);

      async function untilReads(n: number) {
        for (
          let i = 0;
          i < 5 && getConversation.mock.calls.length < readsBefore + n;
          i++
        ) {
          await tick(POLL_MS);
        }
        await tick(0);
        expect(getConversation.mock.calls.length).toBeGreaterThanOrEqual(
          readsBefore + n,
        );
      }

      await untilReads(1);
      // One free read is not final: the retry may still claim just after it.
      expect(result.current.error).toBeNull();

      await untilReads(2);
      expect(result.current.error).toBe(INTERRUPTED);
      expect(result.current.canRetry).toBe(true);
      expect(transcript(result)).toEqual([["user", "q"]]);
    });
  });

  describe("after a stop", () => {
    it("a stop that ends the turn with kept text sets stoppedNotice and offers Try again with no error line", async () => {
      const { result } = await stopped("Partial");
      expect(transcript(result).at(-1)).toEqual(["assistant", "Partial"]);
      expect(result.current.stoppedNotice).toBe(true);
      expect(result.current.error).toBeNull();
      expect(result.current.canRetry).toBe(true);
    });

    it("a stop before any text sets stoppedNotice and offers Try again under the question", async () => {
      const { result } = await stopped("");
      expect(transcript(result).at(-1)).toEqual(["user", "hi"]);
      expect(result.current.stoppedNotice).toBe(true);
      expect(result.current.canRetry).toBe(true);
    });

    it("a turn that ends without a stop leaves stoppedNotice false", async () => {
      const { result } = await loaded(conv(EARLIER));
      const turn = holdTurn();
      const { settled } = await start(result, "hi");
      act(() => {
        turn.handlers.onConversationId("c1");
        turn.handlers.onChunk("Whole");
      });
      await act(async () => {
        turn.end();
        await settled;
      });
      expect(result.current.stoppedNotice).toBe(false);
      expect(result.current.canRetry).toBe(false);
    });

    it("the next send clears stoppedNotice", async () => {
      const { result } = await stopped("Partial");
      holdTurn();
      await start(result, "next");
      expect(result.current.stoppedNotice).toBe(false);
    });

    it("loading another conversation clears stoppedNotice", async () => {
      serve(() => conv(EARLIER));
      const hook = renderHook(({ id }) => useChat(id, null), {
        initialProps: { id: "c1" },
      });
      await tick(0);
      const turn = holdTurn();
      const { settled } = await start(hook.result, "hi");
      act(() => {
        turn.handlers.onConversationId("c1");
        turn.handlers.onChunk("Partial");
      });
      await act(async () => {
        await hook.result.current.stop();
      });
      await act(async () => {
        turn.end();
        await settled;
      });
      expect(hook.result.current.stoppedNotice).toBe(true);

      hook.rerender({ id: "c2" });
      await tick(0);
      expect(hook.result.current.stoppedNotice).toBe(false);
    });

    it("Try again after a stop with kept text sends replace true for the stopped question and hides the kept reply at once", async () => {
      const { result } = await stopped("Partial");
      const question = sentId();
      holdRetry();
      await pressRetry(result);

      const [conversationId, after, replace] = streamRetry.mock.calls[0];
      expect(conversationId).toBe("c1");
      expect(after).toBe(question);
      expect(replace).toBe(true);
      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
      ]);
      expect(result.current.stoppedNotice).toBe(false);
    });

    it("Try again after a stop before any text sends replace false", async () => {
      const { result } = await stopped("");
      const question = sentId();
      holdRetry();
      await pressRetry(result);
      const [, after, replace] = streamRetry.mock.calls[0];
      expect(after).toBe(question);
      expect(replace).toBe(false);
      expect(result.current.stoppedNotice).toBe(false);
    });

    it("the kept reply is gone for good once the retry's prelude arrives, and the new reply shows once", async () => {
      const { result } = await stopped("Partial");
      const question = sentId();
      const retry = holdRetry();
      await pressRetry(result);
      act(() => {
        retry.handlers.onConversationId("c1");
        retry.handlers.onChunk("Fresh reply.");
      });
      serve(() =>
        conv([
          ...EARLIER,
          msg("user", "hi", question),
          msg("assistant", "Fresh reply.", "a2"),
        ]),
      );
      await finish(() => retry.end());

      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
        ["assistant", "Fresh reply."],
      ]);
      expect(result.current.stoppedNotice).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it("a retry after a stop that then fails leaves the question last with the interrupted line, the kept reply gone", async () => {
      const { result } = await stopped("Partial");
      const retry = holdRetry();
      await pressRetry(result);
      act(() => retry.handlers.onConversationId("c1"));
      await finish(() => retry.fail(new ReplyFailedError("reply_failed")));

      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
      ]);
      expect(result.current.error).toBe(INTERRUPTED);
      expect(result.current.canRetry).toBe(true);
    });

    it("a retry after a stop refused by the demo limit restores the kept reply and shows the limit", async () => {
      const { result } = await stopped("Partial");
      streamRetry.mockRejectedValueOnce(new DemoLimitError());
      await pressRetry(result);
      await tick(0);

      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
        ["assistant", "Partial"],
      ]);
      expect(result.current.limited).toBe(true);
    });

    it("a retry after a stop refused with a 404 restores the kept reply under its question and shows the error", async () => {
      const { result } = await stopped("Partial");
      streamRetry.mockRejectedValueOnce(
        new ReplyRefusedError(404, "Conversation not found"),
      );
      await pressRetry(result);
      await tick(0);

      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
        ["assistant", "Partial"],
      ]);
      expect(result.current.error).toBe("Conversation not found");
      expect(result.current.canRetry).toBe(false);
    });

    it("a retry after a stop refused with a 500 never puts the kept reply back and shows what the server holds", async () => {
      const { result } = await stopped("Partial");
      const question = sentId();
      // The claim's delete committed before the failure.
      serve(() => conv([...EARLIER, msg("user", "hi", question)]));
      streamRetry.mockRejectedValueOnce(
        new ReplyRefusedError(500, "Internal Server Error"),
      );
      await pressRetry(result);
      await tick(0);
      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
      ]);

      for (let i = 0; i < 4 && result.current.error === null; i++) {
        await tick(POLL_MS);
      }
      expect(result.current.error).toBe(INTERRUPTED);
      expect(result.current.canRetry).toBe(true);
      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
      ]);
    });

    it("a stopped reply whose stream was lost, brought back by the poll, shows stoppedNotice and is the reply Try again replaces", async () => {
      const { result } = await loaded(conv(EARLIER));
      const turn = holdTurn();
      await start(result, "hi");
      act(() => {
        turn.handlers.onConversationId("c1");
        turn.handlers.onChunk("Partial");
      });
      await act(async () => {
        await result.current.stop();
      });
      const question = sentId();
      serve(() =>
        conv([
          ...EARLIER,
          msg("user", "hi", question),
          msg("assistant", "Partial", "a-kept"),
        ]),
      );
      await finish(() => turn.fail(new ConnectionLostError()));
      for (let i = 0; i < 5 && result.current.stillAnswering; i++) {
        await tick(POLL_MS);
      }
      expect(result.current.stillAnswering).toBe(false);
      expect(transcript(result).at(-1)).toEqual(["assistant", "Partial"]);
      expect(result.current.stoppedNotice).toBe(true);
      expect(result.current.canRetry).toBe(true);

      holdRetry();
      await pressRetry(result);
      const [, after, replace] = streamRetry.mock.calls[0];
      expect(after).toBe(question);
      expect(replace).toBe(true);
      expect(transcript(result)).toEqual([
        ["user", "earlier"],
        ["assistant", "answer"],
        ["user", "hi"],
      ]);
    });

    it("Try again is not offered while a stop request is still in flight", async () => {
      const { result } = await loaded(conv(EARLIER));
      let answer!: (status: number) => void;
      fetchMock.mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            answer = (status) => resolve(new Response(null, { status }));
          }),
      );
      const turn = holdTurn();
      const { settled } = await start(result, "hi");
      act(() => {
        turn.handlers.onConversationId("c1");
        turn.handlers.onChunk("Partial");
      });
      await act(async () => {
        Promise.resolve(result.current.stop()).catch(() => {});
        await vi.advanceTimersByTimeAsync(0);
      });
      await act(async () => {
        turn.end();
        await settled;
      });
      expect(result.current.canRetry).toBe(false);
      await pressRetry(result);
      expect(streamRetry).not.toHaveBeenCalled();

      await act(async () => {
        answer(204);
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.canRetry).toBe(true);
    });

    it("a stop request that fails with an HTTP status after the turn settled clears stoppedNotice and shows the interrupted line when the conversation ends with the user's message", async () => {
      const { result } = await loaded(conv(EARLIER));
      let answer!: (status: number) => void;
      fetchMock.mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            answer = (status) => resolve(new Response(null, { status }));
          }),
      );
      const turn = holdTurn();
      const { settled } = await start(result, "hi");
      act(() => turn.handlers.onConversationId("c1"));
      await act(async () => {
        Promise.resolve(result.current.stop()).catch(() => {});
        await vi.advanceTimersByTimeAsync(0);
      });
      await act(async () => {
        turn.end();
        await settled;
      });
      expect(transcript(result).at(-1)).toEqual(["user", "hi"]);
      expect(result.current.stoppedNotice).toBe(true);

      await act(async () => {
        answer(500);
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.stoppedNotice).toBe(false);
      expect(result.current.error).toBe(INTERRUPTED);
      expect(result.current.canRetry).toBe(true);
    });

    it("a stop request that fails with an HTTP status after a turn that kept text clears stoppedNotice and shows no line", async () => {
      const { result } = await loaded(conv(EARLIER));
      let answer!: (status: number) => void;
      fetchMock.mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            answer = (status) => resolve(new Response(null, { status }));
          }),
      );
      const turn = holdTurn();
      const { settled } = await start(result, "hi");
      act(() => {
        turn.handlers.onConversationId("c1");
        turn.handlers.onChunk("Partial");
      });
      await act(async () => {
        Promise.resolve(result.current.stop()).catch(() => {});
        await vi.advanceTimersByTimeAsync(0);
      });
      await act(async () => {
        turn.end();
        await settled;
      });
      expect(result.current.stoppedNotice).toBe(true);

      await act(async () => {
        answer(500);
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.stoppedNotice).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.canRetry).toBe(false);
    });
  });
});
