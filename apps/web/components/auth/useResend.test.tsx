import { act, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { resendVerification as ResendFn } from "@/lib/authApi";
import {
  ResendStatus,
  useResend,
  type ResendState,
} from "@/components/auth/useResend";

const { resendVerification } = vi.hoisted(() => ({
  resendVerification: vi.fn<typeof ResendFn>(),
}));
vi.mock("@/lib/authApi", () => ({ resendVerification }));

describe("useResend", () => {
  it("starts idle", () => {
    const { result } = renderHook(() => useResend());
    expect(result.current.state).toBe("idle");
  });

  it("sends the email, is sending while in flight, then sent", async () => {
    let settle!: (value: Awaited<ReturnType<typeof ResendFn>>) => void;
    resendVerification.mockReturnValue(new Promise((r) => (settle = r)));
    const { result } = renderHook(() => useResend());
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.resend("a@b.co");
    });
    expect(resendVerification).toHaveBeenCalledExactlyOnceWith("a@b.co");
    expect(result.current.state).toBe("sending");
    await act(async () => {
      settle({ ok: true, data: { status: "check_inbox" } });
      await pending;
    });
    expect(result.current.state).toBe("sent");
  });

  it.each([
    [
      "a rate_limited failure",
      "rate_limited",
      { ok: false, code: "rate_limited" },
    ],
    ["an unknown failure", "error", { ok: false, code: "unknown" }],
    [
      "a validation failure",
      "error",
      { ok: false, code: "validation", detail: [] },
    ],
  ] as const)("%s ends in %s", async (_label, expected, outcome) => {
    resendVerification.mockResolvedValue(outcome);
    const { result } = renderHook(() => useResend());
    await act(() => result.current.resend("a@b.co"));
    expect(result.current.state).toBe(expected);
  });

  it("reset returns to idle", async () => {
    resendVerification.mockResolvedValue({
      ok: true,
      data: { status: "check_inbox" },
    });
    const { result } = renderHook(() => useResend());
    await act(() => result.current.resend("a@b.co"));
    act(() => result.current.reset());
    expect(result.current.state).toBe("idle");
  });

  it("ignores a result that lands after reset", async () => {
    let settle!: (value: Awaited<ReturnType<typeof ResendFn>>) => void;
    resendVerification.mockReturnValue(new Promise((r) => (settle = r)));
    const { result } = renderHook(() => useResend());
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.resend("a@b.co");
    });
    expect(result.current.state).toBe("sending");
    act(() => result.current.reset());
    expect(result.current.state).toBe("idle");
    await act(async () => {
      settle({ ok: true, data: { status: "check_inbox" } });
      await pending;
    });
    expect(result.current.state).toBe("idle");
  });

  it("applies only the latest resend's result", async () => {
    let settleFirst!: (value: Awaited<ReturnType<typeof ResendFn>>) => void;
    let settleSecond!: (value: Awaited<ReturnType<typeof ResendFn>>) => void;
    resendVerification
      .mockReturnValueOnce(new Promise((r) => (settleFirst = r)))
      .mockReturnValueOnce(new Promise((r) => (settleSecond = r)));
    const { result } = renderHook(() => useResend());
    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = result.current.resend("a@b.co");
    });
    act(() => {
      second = result.current.resend("c@d.co");
    });
    expect(resendVerification).toHaveBeenNthCalledWith(1, "a@b.co");
    expect(resendVerification).toHaveBeenNthCalledWith(2, "c@d.co");

    await act(async () => {
      settleFirst({ ok: true, data: { status: "check_inbox" } });
      await first;
    });
    expect(result.current.state).toBe("sending");

    await act(async () => {
      settleSecond({ ok: false, code: "rate_limited" });
      await second;
    });
    expect(result.current.state).toBe("rate_limited");
  });
});

describe("ResendStatus", () => {
  it.each([
    ["sent shows the default copy", "sent", undefined, "Sent."],
    [
      "sent shows the caller's copy",
      "sent",
      "Check your inbox.",
      "Check your inbox.",
    ],
    [
      "rate_limited shows the wait message",
      "rate_limited",
      undefined,
      "Too many attempts — try again in a few minutes.",
    ],
    [
      "error shows the retry message",
      "error",
      undefined,
      "Something went wrong. Please try again.",
    ],
  ] as Array<[string, ResendState, string | undefined, string]>)(
    "%s",
    (_label, state, sentCopy, text) => {
      render(<ResendStatus state={state} sentCopy={sentCopy} />);
      expect(screen.getByText(text)).toBeInTheDocument();
    },
  );

  it.each(["idle", "sending"] as ResendState[])(
    "%s renders nothing",
    (state) => {
      const { container } = render(<ResendStatus state={state} />);
      expect(container).toBeEmptyDOMElement();
    },
  );
});
