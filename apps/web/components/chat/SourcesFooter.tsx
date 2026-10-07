"use client";

import { useState } from "react";

import { type Source } from "@/lib/chatApi";

interface SourcesFooterProps {
  sources: Source[];
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
    <div className="mt-2 border-t border-black/10 pt-2 text-xs dark:border-white/10">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-black/50 dark:text-white/50">Sources</span>
        {[...byDocument.entries()].map(([documentId, group]) => {
          const isOpen = open === documentId;
          return (
            <button
              key={documentId}
              type="button"
              aria-expanded={isOpen}
              onClick={() => setOpen(isOpen ? null : documentId)}
              className={`max-w-full truncate rounded-full border px-2 py-0.5 ${
                isOpen
                  ? "border-foreground/40 bg-black/10 dark:bg-white/15"
                  : "border-black/15 hover:bg-black/5 dark:border-white/20 dark:hover:bg-white/10"
              }`}
            >
              {group.filename}
              <span className="ml-1 text-black/50 dark:text-white/50">
                {group.passages.length}
              </span>
            </button>
          );
        })}
      </div>
      {open && byDocument.has(open) ? (
        <ul className="mt-2 space-y-2">
          {byDocument.get(open)!.passages.map((p) => (
            <li
              key={`${p.document_id}:${p.chunk_idx}`}
              className="whitespace-pre-wrap wrap-break-word rounded-md bg-black/5 px-2 py-1.5 text-black/70 dark:bg-white/5 dark:text-white/70"
            >
              {p.excerpt}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
