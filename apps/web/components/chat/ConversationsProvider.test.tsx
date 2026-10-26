import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type {
  ConversationSummary,
  listConversations as ListConversationsFn,
} from "@/lib/chatApi";
import {
  ConversationsProvider,
  useConversations,
} from "@/components/chat/ConversationsProvider";

const { listConversations } = vi.hoisted(() => ({
  listConversations: vi.fn<typeof ListConversationsFn>(),
}));
vi.mock("@/lib/chatApi", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/chatApi")>("@/lib/chatApi");
  return { ...actual, listConversations };
});

type Held = { resolve: (list: ConversationSummary[]) => void };

// The next listConversations call stays in flight until the test resolves it.
function holdList(): Held {
  const held = {} as Held;
  listConversations.mockImplementationOnce(
    () =>
      new Promise<ConversationSummary[]>((resolve) => {
        held.resolve = resolve;
      }),
  );
  return held;
}

function summary(id: string, title: string): ConversationSummary {
  return {
    id,
    title,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
  };
}

const MOUNT = [summary("00000000-0000-0000-0000-000000000000", "mount")];
const LIST_A = [summary("00000000-0000-0000-0000-00000000000a", "A")];
const LIST_B = [
  summary("00000000-0000-0000-0000-00000000000b", "B"),
  summary("00000000-0000-0000-0000-00000000000c", "B2"),
];

function wrapper({ children }: { children: ReactNode }) {
  return <ConversationsProvider>{children}</ConversationsProvider>;
}

// Settles the provider's own mount-time refresh so it cannot race the
// explicit calls under test.
async function renderSettled() {
  const mount = holdList();
  const hook = renderHook(() => useConversations(), { wrapper });
  await waitFor(() => expect(listConversations).toHaveBeenCalledTimes(1));
  await act(async () => {
    mount.resolve(MOUNT);
  });
  expect(hook.result.current.conversations).toEqual(MOUNT);
  return hook;
}

async function twoRefreshes(result: {
  current: ReturnType<typeof useConversations>;
}) {
  const first = holdList();
  const second = holdList();
  act(() => {
    result.current.refresh();
  });
  act(() => {
    result.current.refresh();
  });
  await waitFor(() => expect(listConversations).toHaveBeenCalledTimes(3));
  return { first, second };
}

describe("ConversationsProvider refresh", () => {
  it("keeps the latest call's list when an earlier call resolves after it", async () => {
    const { result } = await renderSettled();
    const { first, second } = await twoRefreshes(result);

    await act(async () => {
      second.resolve(LIST_B);
    });
    await waitFor(() => expect(result.current.conversations).toEqual(LIST_B));

    await act(async () => {
      first.resolve(LIST_A);
    });
    expect(result.current.conversations).toEqual(LIST_B);
  });

  it("shows the latest call's list when calls resolve in order", async () => {
    const { result } = await renderSettled();
    const { first, second } = await twoRefreshes(result);

    await act(async () => {
      first.resolve(LIST_A);
    });
    await act(async () => {
      second.resolve(LIST_B);
    });
    expect(result.current.conversations).toEqual(LIST_B);
  });
});
