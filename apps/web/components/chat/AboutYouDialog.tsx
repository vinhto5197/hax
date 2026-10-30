"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { getProfile, saveProfile } from "@/lib/profileApi";

// Mirrors the server's cap (ProfileIn, the user_profiles CHECK), which counts
// code points of the stripped text.
const MAX_CHARS = 1000;

type Load = "loading" | "ready" | "failed";

// Rendered by AboutYouProvider through a portal at z-50, above the phone
// drawer (z-40), never inside the account menu or the sidebar: React passes
// synthetic events up the component tree through a portal, so a dialog
// rendered there would hand its keys to the menu's handlers.
export function AboutYouDialog({
  onClose,
  confirmMember,
}: {
  onClose: () => void;
  // Resolves false when the session cookie now belongs to another member: the
  // dialog then closes without saving.
  confirmMember?: () => Promise<boolean>;
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [load, setLoad] = useState<Load>("loading");
  const [saved, setSaved] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  // Until the load returns, the textarea and Save stay disabled: a slow load
  // can never be overwritten by an empty save, nor a late one wipe typing.
  useEffect(() => {
    let cancelled = false;
    panelRef.current?.focus();
    getProfile()
      .then((profile) => {
        if (cancelled) return;
        const about = profile.about ?? "";
        setSaved(about);
        setText(about);
        setLoad("ready");
      })
      .catch(() => {
        if (!cancelled) setLoad("failed");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (load === "ready") textareaRef.current?.focus();
  }, [load]);

  // Looked up on close, never stored on open: the phone drawer (and the
  // account button with it) may have closed while the dialog was up.
  useEffect(() => {
    return () => {
      const button = document.querySelector<HTMLElement>(
        'button[aria-label="Account menu"]',
      );
      if (button && button.offsetParent !== null) {
        button.focus();
        return;
      }
      const composer = document.querySelector<HTMLElement>(
        'textarea[aria-label="Message"]',
      );
      composer?.focus();
    };
  }, []);

  const trimmed = text.trim();
  const count = Array.from(trimmed).length;
  const canSave =
    load === "ready" && !saving && trimmed !== saved && count <= MAX_CHARS;

  function cancel() {
    // A save in flight must finish, so its failure is always reported.
    if (!saving) onClose();
  }

  async function save() {
    if (!canSave) return;
    setSaving(true);
    setSaveFailed(false);
    try {
      if (confirmMember && !(await confirmMember())) {
        onClose();
        return;
      }
      await saveProfile(trimmed);
      onClose();
    } catch {
      setSaveFailed(true);
      setSaving(false);
    }
  }

  // preventDefault in every state: Shell's document-level listener closes the
  // drawer on an Escape it sees un-prevented, which would take the sidebar
  // with it. Stopping propagation would not help: React's own listener sits
  // on the same node as Shell's.
  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Tab") {
      trapTab(event);
      return;
    }
    if (event.key !== "Escape") return;
    event.preventDefault();
    cancel();
  }

  // aria-modal does not stop Tab: keep focus cycling inside the panel.
  function trapTab(event: React.KeyboardEvent) {
    const focusable = Array.from(
      panelRef.current?.querySelectorAll<HTMLElement>(
        "button, textarea, input, select, a[href], [tabindex]:not([tabindex='-1'])",
      ) ?? [],
    ).filter((element) => !element.hasAttribute("disabled"));
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === panelRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    // The backdrop deliberately does nothing on a tap: a stray tap must never
    // close the dialog (or reach the drawer beneath) and lose the typing, nor
    // move focus to the body, where Escape would miss this dialog's handler
    // and reach Shell's, closing the drawer instead.
    <div
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) event.preventDefault();
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="w-full max-w-lg space-y-3 rounded-card border border-border bg-surface-1 p-6 outline-none"
      >
        <h2 id={titleId} className="text-title font-semibold text-ink">
          About you
        </h2>
        <p className="text-body text-ink-2">
          Tell Hax about yourself: what you do, what you know, how you like
          answers. Hax reads this in every conversation.
        </p>
        <textarea
          ref={textareaRef}
          aria-label="About you"
          value={text}
          onChange={(event) => setText(event.target.value)}
          disabled={load !== "ready"}
          readOnly={saving}
          rows={6}
          className="block w-full resize-y rounded-control border border-border-control bg-ground px-3 py-2 text-body text-ink disabled:opacity-50"
        />
        <p
          className={`text-small ${count > MAX_CHARS ? "text-status-failed" : "text-ink-3"}`}
        >
          {count} / {MAX_CHARS}
        </p>
        {load === "failed" ? (
          <p className="text-small text-status-failed">
            Couldn&apos;t load your note. Close and try again.
          </p>
        ) : null}
        {saveFailed ? (
          <p className="text-small text-status-failed">
            Couldn&apos;t save. Try again.
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={cancel}
            className="rounded-control border border-border-control px-4 py-2 text-body text-ink hover:bg-surface-2"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!canSave}
            className="rounded-control bg-accent px-4 py-2 text-body font-medium text-accent-ink disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
