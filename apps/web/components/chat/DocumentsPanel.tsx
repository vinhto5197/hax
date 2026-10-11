"use client";

import {
  type ChangeEvent,
  type MouseEvent,
  useEffect,
  useRef,
  useState,
} from "react";

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
  ready: "text-status-ready",
  failed: "text-status-failed",
  pending: "text-ink-3",
  processing: "text-ink-3",
};

const POLL_INTERVAL_MS = 2500;
const IN_FLIGHT: ReadonlySet<string> = new Set(["pending", "processing"]);

// Failed rows sort above the fold of the capped list, then in-flight, then
// ready; stable within a group.
function statusRank(doc: DocumentSummary): number {
  if (doc.status === "failed") return 0;
  if (IN_FLIGHT.has(doc.status)) return 1;
  return 2;
}

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

  function handleUploadClick(event: MouseEvent<HTMLButtonElement>) {
    // The button lives inside <summary>: a cancelled click skips the summary's
    // activation behaviour, so uploading never toggles the panel. The panel is
    // opened instead, since the new row and any error render inside it.
    event.preventDefault();
    event.currentTarget.closest("details")?.setAttribute("open", "");
    inputRef.current?.click();
  }

  const failedCount = documents.filter((d) => d.status === "failed").length;
  const ordered = [...documents].sort((a, b) => statusRank(a) - statusRank(b));

  return (
    <details
      open
      className="group flex shrink-0 flex-col gap-2 border-t border-border pt-3"
      data-documents-panel
    >
      <summary className="flex cursor-pointer list-none items-center justify-between px-1 text-small font-medium text-ink-2 [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="text-small leading-none transition-transform group-open:rotate-90"
          >
            ▸
          </span>
          Documents
          <span className="font-normal text-ink-3">{documents.length}</span>
          {failedCount > 0 ? (
            <span className="text-caption font-medium text-status-failed">
              · {failedCount} failed
            </span>
          ) : null}
        </span>
        <button
          type="button"
          onClick={handleUploadClick}
          disabled={uploading}
          className="rounded-control border border-border-control px-2 py-0.5 text-caption text-ink hover:bg-surface-2 disabled:opacity-50"
        >
          {uploading ? "Uploading…" : "+ Upload"}
        </button>
      </summary>
      <p className="px-1 text-caption text-ink-3">
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

      {error && <p className="px-1 text-caption text-status-failed">{error}</p>}

      {documents.length === 0 ? (
        <p className="px-1 text-caption text-ink-3">
          No documents yet. Upload a .txt, .md, .pdf or .docx to chat over it.
        </p>
      ) : (
        <ul className="flex max-h-24 flex-col gap-1 overflow-y-auto">
          {ordered.map((doc) => {
            const statusClass = STATUS_STYLES[doc.status] ?? "text-ink-3";
            return (
              // The id is the reach-in point for SourcesFooter's "Show in
              // panel" (scroll + data-flash), which must not share state with
              // this panel.
              <li
                key={doc.id}
                id={`doc-${doc.id}`}
                className="scroll-mt-2 rounded-control px-1 text-small transition-colors duration-500 ease-in-out"
              >
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleDownload(doc)}
                    title="Download"
                    className="flex-1 truncate text-left text-ink hover:underline"
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
                      className={`text-caption font-medium underline decoration-dotted underline-offset-2 ${statusClass}`}
                    >
                      {doc.status}
                    </button>
                  ) : (
                    <span className={`text-caption font-medium ${statusClass}`}>
                      {doc.status}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDelete(doc)}
                    disabled={deletingId === doc.id}
                    aria-label={`Delete ${doc.filename}`}
                    className="shrink-0 px-0.5 text-sm leading-none text-ink-3 hover:text-status-failed disabled:opacity-50"
                  >
                    ×
                  </button>
                </div>
                {doc.error && openErrorIds.has(doc.id) ? (
                  <p className="mt-0.5 text-caption text-status-failed">
                    {doc.error}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </details>
  );
}
