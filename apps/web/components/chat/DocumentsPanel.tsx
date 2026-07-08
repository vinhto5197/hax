"use client";

import { type ChangeEvent, useEffect, useRef, useState } from "react";

import {
  type DocumentSummary,
  deleteDocument,
  listDocuments,
  uploadDocument,
} from "@/lib/chatApi";

// "Data" section: upload a .txt/.md file and watch ingestion status. Ingestion
// runs in the Celery worker (slice 2a), so an upload returns 'pending' and the
// panel polls until it settles to ready|failed.
// Local state (not a Context) — only this panel reads documents for now.
const STATUS_STYLES: Record<string, string> = {
  ready: "text-green-600 dark:text-green-400",
  failed: "text-red-600 dark:text-red-400",
  pending: "text-black/40 dark:text-white/40",
  processing: "text-black/40 dark:text-white/40",
};

// Poll cadence while any doc is still ingesting. ~2.5s balances responsiveness
// against load for a background job that takes seconds.
const POLL_INTERVAL_MS = 2500;
const IN_FLIGHT: ReadonlySet<string> = new Set(["pending", "processing"]);

export function DocumentsPanel() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listDocuments()
      .then(setDocuments)
      .catch(() => {
        // A failed list shouldn't break the chat; leave the panel empty.
      });
  }, []);

  // Poll while any doc is still ingesting, so its status settles to ready|failed
  // without a manual refresh. Keyed off `hasPending`: React re-runs this effect
  // only when that boolean flips, so the interval is created once ingestion
  // starts and torn down (polling stops) once everything has settled — not reset
  // on every poll.
  const hasPending = documents.some((d) => IN_FLIGHT.has(d.status));
  useEffect(() => {
    if (!hasPending) return;
    const id = setInterval(() => {
      listDocuments()
        .then(setDocuments)
        .catch(() => {
          // Transient list failure; the next tick retries.
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [hasPending]);

  async function handleDelete(doc: DocumentSummary) {
    // Deletion is irreversible (drops the stored file + its chunks), so confirm
    // first. window.confirm blocks synchronously, so no second click lands until
    // it's dismissed.
    if (!window.confirm(`Delete "${doc.filename}"? This can't be undone.`)) {
      return;
    }
    setError(null);
    // Guard against a double-delete (a second click after the confirm returns):
    // disable this row's button while its request is in flight.
    setDeletingId(doc.id);
    try {
      await deleteDocument(doc.id);
      // Drop it locally rather than re-fetch — one fewer round-trip, and the list
      // is authoritative on the next natural refresh (mount / upload / poll).
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed.");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const doc = await uploadDocument(file);
      // Ingestion runs in the worker now, so the upload returns immediately at
      // 'pending'. Prepend it; the polling effect updates its status to
      // ready|failed as the worker finishes (a failed doc shows as a red row with
      // its error on hover).
      setDocuments((prev) => [doc, ...prev]);
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
              className="flex items-center gap-2 px-1 text-xs"
              title={doc.error ?? undefined}
            >
              <span className="flex-1 truncate text-black/70 dark:text-white/70">
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
              <button
                type="button"
                onClick={() => handleDelete(doc)}
                disabled={deletingId === doc.id}
                aria-label={`Delete ${doc.filename}`}
                className="shrink-0 px-0.5 text-sm leading-none text-black/30 hover:text-red-600 disabled:opacity-50 dark:text-white/30 dark:hover:text-red-400"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
