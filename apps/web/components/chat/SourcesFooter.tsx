"use client";

import { useState } from "react";

import { type Source } from "@/lib/chatApi";

interface SourcesFooterProps {
  sources: Source[];
}

const FLASH_MS = 1200;

// Reaches the documents panel by DOM id: its state is local to it, and a
// provenance link must not couple the two components; opens the panel if
// collapsed. The sources are a snapshot that outlives the document, so a
// missing row is normal.
function showInPanel(documentId: string) {
  const row = document.getElementById(`doc-${documentId}`);
  if (!row) return;
  row.closest("details")?.setAttribute("open", "");
  row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  row.setAttribute("data-flash", "true");
  window.setTimeout(() => row.removeAttribute("data-flash"), FLASH_MS);
}

// Provenance under an assistant reply: the passages the model had in front
// of it, grouped by document. Shown only on committed turns — the live
// bubble has the status line instead. "Searched", not "cited": nothing here
// claims which sentence rests on which passage.
export function SourcesFooter({ sources }: SourcesFooterProps) {
  const [open, setOpen] = useState<string | null>(null);
  if (sources.length === 0) return null;

  // Group by document, preserving first-seen order; passages in document order.
  const byDocument = new Map<
    string,
    { filename: string; passages: Source[] }
  >();
  for (const s of sources) {
    const group = byDocument.get(s.document_id) ?? {
      filename: s.filename,
      passages: [],
    };
    group.passages.push(s);
    byDocument.set(s.document_id, group);
  }
  for (const group of byDocument.values()) {
    group.passages.sort((a, b) => a.chunk_idx - b.chunk_idx);
  }

  return (
    <div className="mt-3 border-t border-border pt-2 text-small">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-caption font-medium text-ink-3">Sources</span>
        {[...byDocument.entries()].map(([documentId, group]) => {
          const isOpen = open === documentId;
          return (
            <button
              key={documentId}
              type="button"
              aria-expanded={isOpen}
              onClick={() => setOpen(isOpen ? null : documentId)}
              className={`max-w-full truncate rounded-full border px-2.5 py-0.5 text-ink ${
                isOpen
                  ? "border-ink-2 bg-surface-3"
                  : "border-border-control hover:bg-surface-2"
              }`}
            >
              {group.filename}
              <span className={`ml-1 ${isOpen ? "text-ink-2" : "text-ink-3"}`}>
                {group.passages.length}
              </span>
            </button>
          );
        })}
      </div>
      {open && byDocument.has(open) ? (
        <>
          <button
            type="button"
            onClick={() => showInPanel(open)}
            className="mt-2 text-small text-ink-2 underline-offset-2 hover:underline"
          >
            Show in panel
          </button>
          <ul className="mt-1 space-y-2">
            {byDocument.get(open)!.passages.map((p) => (
              <li
                key={`${p.document_id}:${p.chunk_idx}`}
                className="whitespace-pre-wrap wrap-break-word rounded-control bg-surface-2 px-3 py-2 text-ink-2"
              >
                {p.excerpt}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}
