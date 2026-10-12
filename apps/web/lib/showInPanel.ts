// "Show in panel" crosses from a reply's sources footer to the documents
// panel: the footer asks (an event on `window`), the shell answers by
// revealing the row once a panel is mounted. The row's DOM id (`doc-<id>`)
// is the only coupling; a missing row is normal, since sources are a
// snapshot that outlives the document.

export const SHOW_DOCUMENT_EVENT = "hax:show-document";

const FLASH_MS = 1200;

export function requestShowInPanel(documentId: string): void {
  window.dispatchEvent(
    new CustomEvent(SHOW_DOCUMENT_EVENT, { detail: { documentId } }),
  );
}

export function revealDocumentRow(documentId: string): boolean {
  const row = document.getElementById(`doc-${documentId}`);
  if (!row) return false;
  row.closest("details")?.setAttribute("open", "");
  row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  row.setAttribute("data-flash", "true");
  window.setTimeout(() => row.removeAttribute("data-flash"), FLASH_MS);
  return true;
}
