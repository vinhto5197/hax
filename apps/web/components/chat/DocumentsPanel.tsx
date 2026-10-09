"use client";

import { type ChangeEvent, useEffect, useRef, useState } from "react";

import {
  type DocumentSummary,
  deleteDocument,
  downloadDocument,
  listDocuments,
  uploadDocument,
} from "@/lib/chatApi";

// Upload a .txt/.md/.pdf/.docx file and watch ingestion status: uploads return 'pending'
// and the panel polls until ready|failed. Local state — only this panel reads it.
const STATUS_STYLES: Record<string, string> = {
  ready: "text-green-600 dark:text-green-400",
  failed: "text-red-600 dark:text-red-400",
  pending: "text-black/40 dark:text-white/40",
  processing: "text-black/40 dark:text-white/40",
};

const POLL_INTERVAL_MS = 2500;
const IN_FLIGHT: ReadonlySet<string> = new Set(["pending", "processing"]);

export function DocumentsPanel() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Failed documents whose reason is shown inline (tap the status; each
  // toggles on its own).
  const [openErrorIds, setOpenErrorIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listDocuments()
      .then(setDocuments)
      .catch(() => {
        // A failed list shouldn't break the chat; leave the panel empty.
      });
  }, []);

  // Poll while any doc is ingesting. Keyed off the boolean so the interval is
  // created when ingestion starts and torn down when everything settles — not
  // reset on every poll.
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
    // Irreversible (drops the stored file + chunks) — confirm first.
    if (!window.confirm(`Delete "${doc.filename}"? This can't be undone.`)) {
      return;
    }
    setError(null);
    setDeletingId(doc.id);
    try {
      await deleteDocument(doc.id);
      // Drop locally rather than re-fetch; the list is authoritative on the
      // next natural refresh.
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed.");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleDownload(doc: DocumentSummary) {
    setError(null);
    try {
      await downloadDocument(doc.id, doc.filename);
    } catch {
      setError("Couldn't download that file.");
    }
  }

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const doc = await uploadDocument(file);
      // Upload returns at 'pending'; the polling effect settles the status.
      setDocuments((prev) => [doc, ...prev]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
      // A file input fires onChange only on value change — clear it so
      // re-selecting the same file isn't a silent no-op.
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
      <p className="px-1 text-xs text-black/40 dark:text-white/40">
        PDF, Word (.docx), .txt or .md. Text PDFs only, up to 5 MB; plain text
        up to 256 KB.
      </p>
      {/* Hidden file control; the styled button above proxies to it. */}
      <input
        ref={inputRef}
        type="file"
        accept=".txt,.md,.pdf,.docx"
        onChange={handleFile}
        className="hidden"
      />

      {error && (
        <p className="px-1 text-xs text-red-600 dark:text-red-400">{error}</p>
      )}

      {documents.length === 0 ? (
        <p className="px-1 text-xs text-black/40 dark:text-white/40">
          No documents yet. Upload a .txt, .md, .pdf or .docx to chat over it.
        </p>
      ) : (
        <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto">
          {documents.map((doc) => {
            const statusClass =
              STATUS_STYLES[doc.status] ?? "text-black/40 dark:text-white/40";
            return (
              // The id is the reach-in point for SourcesFooter's "Show in
              // panel" (scroll + data-flash), which must not share state with
              // this panel.
              <li
                key={doc.id}
                id={`doc-${doc.id}`}
                className="scroll-mt-2 rounded px-1 text-xs transition-colors duration-500 ease-in-out"
              >
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleDownload(doc)}
                    title="Download"
                    className="flex-1 truncate text-left text-black/70 hover:underline dark:text-white/70"
                  >
                    {doc.filename}
                  </button>
                  {doc.error ? (
                    // A failed document's reason opens on tap, not hover.
                    <button
                      type="button"
                      onClick={() =>
                        setOpenErrorIds((ids) => {
                          const next = new Set(ids);
                          if (!next.delete(doc.id)) next.add(doc.id);
                          return next;
                        })
                      }
                      aria-expanded={openErrorIds.has(doc.id)}
                      className={`underline decoration-dotted underline-offset-2 ${statusClass}`}
                    >
                      {doc.status}
                    </button>
                  ) : (
                    <span className={statusClass}>{doc.status}</span>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDelete(doc)}
                    disabled={deletingId === doc.id}
                    aria-label={`Delete ${doc.filename}`}
                    className="shrink-0 px-0.5 text-sm leading-none text-black/30 hover:text-red-600 disabled:opacity-50 dark:text-white/30 dark:hover:text-red-400"
                  >
                    ×
                  </button>
                </div>
                {doc.error && openErrorIds.has(doc.id) ? (
                  <p className="mt-0.5 text-red-600 dark:text-red-400">
                    {doc.error}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
