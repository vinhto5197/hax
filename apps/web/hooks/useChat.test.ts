import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ConversationDetail,
  getConversation as GetConversationFn,
  Source,
  StreamHandlers,
  streamChat as StreamChatFn,
} from "@/lib/chatApi";
import {
  ConnectionLostError,
  ReplyFailedError,
  TurnInProgressError,
} from "@/lib/chatApi";
import { useChat } from "@/hooks/useChat";

const { getConversation, streamChat, DemoLimitError } = vi.hoisted(() => ({
  getConversation: vi.fn<typeof GetConversationFn>(),
  streamChat: vi.fn<typeof StreamChatFn>(),
  DemoLimitError: class DemoLimitError extends Error {
    constructor() {
      super("demo_limit");
      this.name = "DemoLimitError";
    }
  },
}));
vi.mock("@/lib/chatApi", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/chatApi")>("@/lib/chatApi");
  return {
    getConversation,
    streamChat,
    DemoLimitError,
    TurnInProgressError: actual.TurnInProgressError,
    ReplyFailedError: actual.ReplyFailedError,
    ConnectionLostError: actual.ConnectionLostError,
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
      role: "user",
      content: "question",
      created_at: "2026-10-01T00:00:01Z",
    });
    expect(result.current.messages[1]).toEqual({
      role: "assistant",
      content: "answer",
      created_at: "2026-10-01T00:00:02Z",
      sources: [source("d1", 0)],
    });
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
      const message = (content: string) => ({
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
