import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsPanel } from "@/components/chat/DocumentsPanel";
import {
  listDocuments,
  uploadDocument,
  type DocumentSummary,
} from "@/lib/chatApi";

vi.mock("@/lib/chatApi", () => ({
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  deleteDocument: vi.fn(),
  downloadDocument: vi.fn(),
}));

function doc(overrides: Partial<DocumentSummary>): DocumentSummary {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    filename: "notes.pdf",
    mime_type: "application/pdf",
    size_bytes: 1024,
    status: "ready",
    error: null,
    created_at: "2026-10-28T10:00:00Z",
    updated_at: "2026-10-28T10:00:00Z",
    ...overrides,
  };
}

// The config's mockReset clears implementations before each test, so the
// list is queued here; every poll gets the same list, so no state changes.
function serve(docs: DocumentSummary[]) {
  vi.mocked(listDocuments).mockResolvedValue(docs);
}

beforeEach(() => {
  // matches: false keeps the panel's <details> open by default.
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
});

describe("DocumentsPanel status labels", () => {
  it("shows an in-flight row as 'Processing…' with a hint and aria-busy", async () => {
    serve([doc({ filename: "pending.pdf", status: "pending" })]);
    render(<DocumentsPanel />);

    const name = await screen.findByText("pending.pdf");
    const row = name.closest("li");
    expect(row).toHaveAttribute("aria-busy", "true");

    const label = screen.getByTitle("Usually under a minute");
    expect(label).toHaveTextContent("Processing…");
    expect(row).toContainElement(label);
    expect(screen.queryByText("pending")).toBeNull();
  });

  it("keeps a ready row's raw status word and no aria-busy", async () => {
    serve([doc({ filename: "ready.pdf", status: "ready" })]);
    render(<DocumentsPanel />);

    const row = (await screen.findByText("ready.pdf")).closest("li");
    expect(row).toHaveTextContent("ready");
    expect(row).not.toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText(/Processing…/)).toBeNull();
  });

  it("reveals a failed row's reason only after clicking 'failed'", async () => {
    const reason = "Couldn't read that PDF.";
    serve([doc({ filename: "broken.pdf", status: "failed", error: reason })]);
    render(<DocumentsPanel />);

    await screen.findByText("broken.pdf");
    const hidden = screen.queryByText(reason);
    if (hidden) expect(hidden).not.toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "failed" }));
    expect(await screen.findByText(reason)).toBeVisible();
  });
});

const EMPTY =
  "No documents yet. Upload a .txt, .md, .pdf or .docx to chat over it.";

function summaryOf(container: HTMLElement) {
  return container.querySelector("summary") as HTMLElement;
}

// The count is the summary's only all-digit text.
function countIn(container: HTMLElement) {
  return within(summaryOf(container)).queryByText(/^\d+$/);
}

function skeletonIn(container: HTMLElement) {
  return container.querySelector('details [data-skeleton="documents"]');
}

describe("DocumentsPanel loading", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("while the first list is in flight it shows the skeleton, no count and no empty line", async () => {
    vi.mocked(listDocuments).mockReturnValue(new Promise(() => {}));
    const { container } = render(<DocumentsPanel />);
    await act(async () => {});

    const skeleton = skeletonIn(container);
    expect(skeleton).not.toBeNull();
    expect(skeleton!.querySelectorAll("[data-skeleton-row]")).toHaveLength(3);
    expect(countIn(container)).toBeNull();
    expect(screen.queryByText(EMPTY)).toBeNull();
  });

  it("hides the skeleton from assistive tech", async () => {
    vi.mocked(listDocuments).mockReturnValue(new Promise(() => {}));
    const { container } = render(<DocumentsPanel />);
    await act(async () => {});

    expect(skeletonIn(container)).toHaveAttribute("aria-hidden", "true");
  });

  it("marks the panel aria-busy while the first list is in flight", async () => {
    vi.mocked(listDocuments).mockReturnValue(new Promise(() => {}));
    const { container } = render(<DocumentsPanel />);
    await act(async () => {});

    expect(container.querySelector("[data-documents-panel]")).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("clears the panel's aria-busy once the first list has loaded", async () => {
    serve([doc({})]);
    const { container } = render(<DocumentsPanel />);
    await within(summaryOf(container)).findByText("1", { exact: true });

    const panel = container.querySelector("[data-documents-panel]");
    expect(panel).not.toBeNull();
    expect(panel).not.toHaveAttribute("aria-busy", "true");
  });

  it("clears the panel's aria-busy after a failed first list", async () => {
    vi.mocked(listDocuments).mockRejectedValue(new Error("API 500"));
    const { container } = render(<DocumentsPanel />);
    await act(async () => {});
    await act(async () => {});

    expect(skeletonIn(container)).toBeNull();
    const panel = container.querySelector("[data-documents-panel]");
    expect(panel).not.toBeNull();
    expect(panel).not.toHaveAttribute("aria-busy", "true");
  });

  it("a failed first list shows no skeleton, no count and no empty line", async () => {
    vi.mocked(listDocuments).mockRejectedValue(new Error("API 500"));
    const { container } = render(<DocumentsPanel />);
    await act(async () => {});
    await act(async () => {});

    expect(skeletonIn(container)).toBeNull();
    expect(countIn(container)).toBeNull();
    expect(screen.queryByText(EMPTY)).toBeNull();
    expect(screen.getByText("+ Upload")).toBeInTheDocument();
  });

  it("a poll's list after a failed first list shows the count", async () => {
    vi.useFakeTimers();
    const pending = doc({ filename: "pending.txt", status: "pending" });
    const ready = doc({ filename: "pending.txt", status: "ready" });
    vi.mocked(listDocuments)
      .mockRejectedValueOnce(new Error("API 500"))
      .mockResolvedValue([ready]);
    vi.mocked(uploadDocument).mockResolvedValue(pending);

    const { container } = render(<DocumentsPanel />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(skeletonIn(container)).toBeNull();
    expect(countIn(container)).toBeNull();

    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File(["hello"], "pending.txt", { type: "text/plain" });
    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(uploadDocument).toHaveBeenCalledTimes(1);
    expect(screen.getByText("pending.txt")).toBeInTheDocument();
    // An upload is not a list: the count waits for one.
    expect(countIn(container)).toBeNull();

    // One poll interval per act(), so React commits each list before the
    // next tick, as it does between real ticks; a single 30 s act() keeps
    // the interval firing on the stale pending list.
    for (let tick = 0; tick < 12; tick++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_500);
      });
    }
    expect(vi.mocked(listDocuments).mock.calls.length).toBeGreaterThanOrEqual(
      2,
    );
    expect(
      within(summaryOf(container)).getByText("1", { exact: true }),
    ).toBeInTheDocument();
  });

  it("keeps polling while any document is in flight, and stops once every one is ready", async () => {
    vi.useFakeTimers();
    const a = (status: DocumentSummary["status"]) =>
      doc({
        id: "00000000-0000-0000-0000-00000000000a",
        filename: "a.pdf",
        status,
      });
    const b = (status: DocumentSummary["status"]) =>
      doc({
        id: "00000000-0000-0000-0000-00000000000b",
        filename: "b.pdf",
        status,
      });
    // The first list has both in flight; the first poll finds only a.pdf
    // ready; the second finds both ready.
    vi.mocked(listDocuments)
      .mockResolvedValueOnce([a("processing"), b("processing")])
      .mockResolvedValueOnce([a("ready"), b("processing")])
      .mockResolvedValue([a("ready"), b("ready")]);
    const calls = () => vi.mocked(listDocuments).mock.calls.length;

    render(<DocumentsPanel />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(calls()).toBe(1);

    // First poll, at exactly 2.5 s: one document is ready, one is not, so
    // the polling goes on.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_499);
    });
    expect(calls()).toBe(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(calls()).toBe(2);
    expect(screen.getAllByText("ready")).toHaveLength(1);

    // Second poll: a repeating poll, not a one-shot timer, fetches again.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_500);
    });
    expect(calls()).toBe(3);
    expect(screen.getAllByText("ready")).toHaveLength(2);

    // Every document is ready: no more list requests.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(calls()).toBe(3);
  });
});

describe("DocumentsPanel upload during the first list", () => {
  const OLD_ID = "00000000-0000-0000-0000-000000000001";
  const FRESH_ID = "00000000-0000-0000-0000-000000000002";
  const old = doc({ id: OLD_ID, filename: "old.pdf", status: "ready" });

  afterEach(() => {
    vi.useRealTimers();
  });

  // Holds the first list, uploads fresh.txt (resolving while that list is
  // still in flight), then lands the held list without the upload. No timer
  // is advanced past 0, so no poll can run before the caller's assertions.
  async function uploadThenLandStaleList() {
    vi.useFakeTimers();
    let resolveList: (docs: DocumentSummary[]) => void = () => {};
    const held = new Promise<DocumentSummary[]>((r) => {
      resolveList = r;
    });
    vi.mocked(listDocuments).mockReturnValueOnce(held);
    vi.mocked(uploadDocument).mockResolvedValue(
      doc({ id: FRESH_ID, filename: "fresh.txt", status: "pending" }),
    );

    const { container } = render(<DocumentsPanel />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File(["hello"], "fresh.txt", { type: "text/plain" });
    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(uploadDocument).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveList([old]);
      await vi.advanceTimersByTimeAsync(0);
    });
    return container;
  }

  it("an upload that resolves before the first list keeps its row when that list lands without it", async () => {
    // Any later list never lands, so only the held list can be on screen.
    vi.mocked(listDocuments).mockReturnValue(new Promise(() => {}));
    await uploadThenLandStaleList();

    expect(screen.getByText("fresh.txt")).toBeInTheDocument();
    expect(screen.getByText("old.pdf")).toBeInTheDocument();
  });

  it("a later list that contains the uploaded document takes over its row", async () => {
    vi.mocked(listDocuments).mockResolvedValue([
      old,
      doc({ id: FRESH_ID, filename: "fresh.txt", status: "ready" }),
    ]);
    await uploadThenLandStaleList();
    expect(screen.getByText("fresh.txt")).toBeInTheDocument();
    expect(screen.getByText("old.pdf")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_500);
    });

    const names = screen.getAllByText("fresh.txt");
    expect(names).toHaveLength(1);
    expect(names[0].closest("li")).not.toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("old.pdf")).toBeInTheDocument();
  });

  it("a list requested after the upload that lacks it drops the row and stops polling", async () => {
    // The document was deleted elsewhere before any list carried it.
    vi.mocked(listDocuments).mockResolvedValue([old]);
    await uploadThenLandStaleList();
    expect(screen.getByText("fresh.txt")).toBeInTheDocument();
    expect(screen.getByText("old.pdf")).toBeInTheDocument();

    // The pending row keeps the poll running; this tick's list was
    // requested after the upload resolved.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_500);
    });
    expect(screen.queryByText("fresh.txt")).toBeNull();
    expect(screen.getByText("old.pdf")).toBeInTheDocument();
    const settled = vi.mocked(listDocuments).mock.calls.length;

    for (let tick = 0; tick < 12; tick++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_500);
      });
    }
    expect(vi.mocked(listDocuments).mock.calls.length).toBe(settled);
  });
});
