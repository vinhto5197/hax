import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RouteError from "@/app/error";

const GUARD = "hax:chunk-reload";

let reload: ReturnType<typeof vi.fn>;

beforeEach(() => {
  sessionStorage.clear();
  reload = vi.fn();
  // jsdom's location.reload is not configurable on the instance; the config's
  // unstubGlobals restores the real location after each test.
  vi.stubGlobal("location", { ...window.location, reload });
});

afterEach(() => {
  sessionStorage.clear();
});

function chunkError(): Error {
  const error = new Error("Loading chunk app/page failed.");
  error.name = "ChunkLoadError";
  return error;
}

describe("RouteError", () => {
  it("reloads once on a ChunkLoadError and sets the guard", async () => {
    render(<RouteError error={chunkError()} reset={() => {}} />);
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(sessionStorage.getItem(GUARD)).not.toBeNull();
    expect(screen.queryByText(/something went wrong/i)).toBeNull();
  });

  it("reloads on a 'Loading chunk' message", async () => {
    const error = new Error("Loading chunk 42 failed.");
    render(<RouteError error={error} reset={() => {}} />);
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  });

  it("shows the card instead when the guard is already set", async () => {
    sessionStorage.setItem(GUARD, "1");
    render(<RouteError error={chunkError()} reset={() => {}} />);
    expect(
      await screen.findByText(/something went wrong/i),
    ).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
  });

  it("shows the card on another error; Retry calls reset", async () => {
    const reset = vi.fn();
    render(<RouteError error={new Error("boom")} reset={reset} />);
    expect(
      await screen.findByText(/something went wrong/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(reset).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
  });
});
