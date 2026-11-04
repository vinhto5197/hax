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

  it("stops polling once every document is ready", async () => {
    vi.useFakeTimers();
    vi.mocked(listDocuments)
      .mockResolvedValueOnce([doc({ status: "processing" })])
      .mockResolvedValue([doc({ status: "ready" })]);

    render(<DocumentsPanel />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // One poll tick turns the row ready.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_500);
    });
    expect(screen.getByText("ready")).toBeInTheDocument();
    const settled = vi.mocked(listDocuments).mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(vi.mocked(listDocuments).mock.calls.length).toBe(settled);
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
});
