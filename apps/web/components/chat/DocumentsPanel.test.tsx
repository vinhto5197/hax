import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsPanel } from "@/components/chat/DocumentsPanel";
import { listDocuments, type DocumentSummary } from "@/lib/chatApi";

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
