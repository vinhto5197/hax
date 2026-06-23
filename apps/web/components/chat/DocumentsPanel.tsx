"use client";

import { type ChangeEvent, useEffect, useRef, useState } from "react";

import {
  type DocumentSummary,
  listDocuments,
  uploadDocument,
} from "@/lib/chatApi";

// Slice-1 "Data" section: upload a .txt/.md file and see ingestion status.
// Local state (not a Context) — only this panel reads documents for now.
const STATUS_STYLES: Record<string, string> = {
  ready: "text-green-600 dark:text-green-400",
  failed: "text-red-600 dark:text-red-400",
  pending: "text-black/40 dark:text-white/40",
  processing: "text-black/40 dark:text-white/40",
};

export function DocumentsPanel() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listDocuments()
      .then(setDocuments)
      .catch(() => {
        // A failed list shouldn't break the chat; leave the panel empty.
      });
  }, []);

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const doc = await uploadDocument(file);
      // Prepend the new doc; it already carries its final ingestion status.
      setDocuments((prev) => [doc, ...prev]);
      // A failed ingest still returns 200, so surface its cause in the banner
      // instead of only as a quiet red row.
      if (doc.status === "failed") {
        setError(doc.error ?? "Ingestion failed.");
      }
    } catch (err) {
      // The other failure channel: uploadDocument throws on a non-2xx/network
      // error (400 wrong type, 413 too big, …) — distinct from the 200-with-
      // failed-status case handled just above.
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
      // A file input fires onChange only when its value changes, so clear it —
      // otherwise re-selecting the same file (e.g. to retry) is a silent no-op.
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="flex shrink-0 flex-col gap-2 border-t border-black/10 pt-3 dark:border-white/10">
      <div className="flex items-center justify-between px-1">
        <span className="text-xs font-medium text-black/60 dark:text-white/60">
          Data
        </span>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="text-xs text-black/60 hover:text-foreground disabled:opacity-50 dark:text-white/60"
        >
          {uploading ? "Uploading…" : "+ Upload"}
        </button>
      </div>
      {/* The real file control is hidden; the styled button above proxies to it
          via inputRef.current.click(). The arrow wrapper on that onClick matters:
          a bare `inputRef.current?.click` reads .current at render time (null
          before mount) — the arrow defers the lookup until the click fires. */}
      <input
        ref={inputRef}
        type="file"
        accept=".txt,.md,text/plain,text/markdown"
        onChange={handleFile}
        className="hidden"
      />

      {error && (
        <p className="px-1 text-xs text-red-600 dark:text-red-400">{error}</p>
      )}

      {documents.length === 0 ? (
        <p className="px-1 text-xs text-black/40 dark:text-white/40">
          No documents yet.
        </p>
      ) : (
        <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto">
          {documents.map((doc) => (
            // `title` shows doc.error on hover. `?? undefined` (not null): React
            // omits the attribute when the value is undefined, and the title prop
            // type is string | undefined, not string | null.
            <li
              key={doc.id}
              className="flex items-center justify-between gap-2 px-1 text-xs"
              title={doc.error ?? undefined}
            >
              <span className="truncate text-black/70 dark:text-white/70">
                {doc.filename}
              </span>
              <span
                className={
                  STATUS_STYLES[doc.status] ??
                  "text-black/40 dark:text-white/40"
                }
              >
                {doc.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
