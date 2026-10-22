import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  ConversationDetail,
  getConversation as GetConversationFn,
  Source,
  StreamHandlers,
  streamChat as StreamChatFn,
} from "@/lib/chatApi";
import { TurnInProgressError } from "@/lib/chatApi";
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

  it("a stream error after text shows the error and keeps the partial reply", async () => {
    const onTurnComplete = vi.fn();
    const result = await newChatTurn(
      holdTurn(),
      (h) => h.onChunk("partial"),
      (t) => t.fail(new Error("API 502: Bad Gateway")),
      { onTurnComplete },
    );
    expect(onTurnComplete).not.toHaveBeenCalled();
    expect(result.current.error).toBe("API 502: Bad Gateway");
    expect(result.current.isLoading).toBe(false);
    expect(result.current.messages[1]).toMatchObject({
      role: "assistant",
      content: "partial",
    });
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
