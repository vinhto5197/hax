import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsPanel } from "@/components/chat/DocumentsPanel";
import {
  downloadDocument,
  listDocuments,
  type DocumentSummary,
} from "@/lib/chatApi";

vi.mock("@/lib/chatApi", () => ({
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  deleteDocument: vi.fn(),
  downloadDocument: vi.fn(),
}));

// "ready" is terminal: the panel does not poll.
const REPORT: DocumentSummary = {
  id: "0b6f3c1e-8d2a-4f6b-9a1e-2c3d4e5f6a7b",
  filename: "report.pdf",
  mime_type: "application/pdf",
  size_bytes: 2048,
  status: "ready",
  error: null,
  created_at: "2026-10-01T12:00:00Z",
  updated_at: "2026-10-01T12:00:05Z",
};

beforeEach(() => {
  // The config's mockReset clears return values, so they are set per test.
  vi.mocked(listDocuments).mockResolvedValue([REPORT]);
  vi.mocked(downloadDocument).mockResolvedValue(undefined);
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

describe("DocumentsPanel filename download", () => {
  it("names the filename control 'Download <filename>' with a 'Download' title", async () => {
    render(<DocumentsPanel />);
    const button = await screen.findByRole("button", {
      name: "Download report.pdf",
    });
    expect(button).toHaveAttribute("title", "Download");
  });

  it("downloads the document once on a click, by id and filename", async () => {
    render(<DocumentsPanel />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Download report.pdf" }),
    );
    expect(downloadDocument).toHaveBeenCalledTimes(1);
    expect(downloadDocument).toHaveBeenCalledWith(REPORT.id, "report.pdf");
  });
});
