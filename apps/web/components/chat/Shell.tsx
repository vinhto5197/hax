"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useConversations } from "@/components/chat/ConversationsProvider";
import { Sidebar } from "@/components/chat/Sidebar";
import { Wordmark } from "@/components/Wordmark";
import { DESKTOP, SHORT, useMediaQuery } from "@/lib/media";
import { SHOW_DOCUMENT_EVENT, revealDocumentRow } from "@/lib/showInPanel";

const REVEAL_POLL_MS = 100;
const REVEAL_TIMEOUT_MS = 2000;

// The shell owns the drawer, which exists only on a phone shell: a viewport
// narrower than `md` or shorter than 500 px (a landscape phone). The sidebar
// is mounted once at a time: in the static column on desktop, in the drawer
// on a phone while it is open, nowhere while it is closed. "Show in panel"
// and the documents poll depend on that single mount. The drawer closes on
// navigation so a tap on a conversation does not leave it covering the page.
export function Shell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  // The server cannot know the viewport, so it renders the desktop shell; the
  // static column is also CSS-hidden below `md` and under `short`, which keeps
  // a phone's first paint free of the sidebar until the client measures and
  // unmounts it.
  const isDesktop = useMediaQuery(DESKTOP, true);
  const isShort = useMediaQuery(SHORT, false);
  const phoneShell = !isDesktop || isShort;
  const { startNewChat } = useConversations();
  const menuRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const pendingDocRef = useRef<string | null>(null);
  // The control that opened the drawer, to return focus to on close.
  const openerRef = useRef<HTMLElement | null>(null);

  // Route change closes the drawer (the back button included), and so does
  // crossing to desktop with it open. Adjusted during render rather than in an
  // effect so the closed state never paints late.
  const [seenPathname, setSeenPathname] = useState(pathname);
  if (pathname !== seenPathname) {
    setSeenPathname(pathname);
    setOpen(false);
  }
  const drawerOpen = open && phoneShell;
  if (open && !phoneShell) setOpen(false);

  // "Show in panel" (lib/showInPanel.ts): with the sidebar in the static
  // column the row is revealed at once; on a phone it is not mounted, so the
  // id waits for the drawer to open.
  useEffect(() => {
    function onShowDocument(event: Event) {
      const { documentId } = (event as CustomEvent<{ documentId: string }>)
        .detail;
      if (!phoneShell) {
        revealDocumentRow(documentId);
        return;
      }
      pendingDocRef.current = documentId;
      openerRef.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      setOpen(true);
    }
    window.addEventListener(SHOW_DOCUMENT_EVENT, onShowDocument);
    return () => {
      window.removeEventListener(SHOW_DOCUMENT_EVENT, onShowDocument);
      // A request made on one shell does not carry to the other.
      pendingDocRef.current = null;
    };
  }, [phoneShell]);

  useEffect(() => {
    if (!drawerOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      // A menu or dialog inside the drawer marks the Escape it handled as
      // defaultPrevented; that one closes only itself.
      if (event.key === "Escape" && !event.defaultPrevented) setOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Focus follows the dialog in, and returns to the control that opened it.
    const opener = openerRef.current ?? menuRef.current;
    openerRef.current = null;
    const panel = panelRef.current;
    panel?.focus();
    // The drawer's documents panel fetches its list after mount, so a pending
    // reveal may find no row yet: poll briefly, until the row appears or the
    // drawer closes.
    const pending = pendingDocRef.current;
    pendingDocRef.current = null;
    let revealTimer: number | undefined;
    if (pending) {
      const deadline = Date.now() + REVEAL_TIMEOUT_MS;
      const attempt = () => {
        if (revealDocumentRow(pending) || Date.now() >= deadline) return;
        revealTimer = window.setTimeout(attempt, REVEAL_POLL_MS);
      };
      attempt();
    }
    return () => {
      window.clearTimeout(revealTimer);
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      // Never pull focus out of another open modal (About you, rendered above
      // the drawer): a drawer closed by a rotation would otherwise take the
      // cursor out of the text being typed. Focus is checked at close.
      const modal = document.activeElement?.closest(
        '[role="dialog"][aria-modal="true"]',
      );
      if (modal && modal !== panel) return;
      opener?.focus();
    };
  }, [drawerOpen]);

  const close = () => setOpen(false);

  return (
    <div className="flex h-dvh">
      {phoneShell ? null : (
        <div className="hidden w-72 shrink-0 md:block short:hidden">
          <Sidebar />
        </div>
      )}
      {drawerOpen ? (
        <div className="fixed inset-0 z-40">
          <button
            type="button"
            aria-label="Close menu"
            tabIndex={-1}
            onClick={close}
            className="absolute inset-0 bg-black/40"
          />
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label="Menu"
            tabIndex={-1}
            className="absolute inset-y-0 left-0 w-72 max-w-[85vw] bg-ground shadow-xl outline-none"
          >
            <Sidebar onNavigate={close} />
          </div>
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col" inert={drawerOpen}>
        {/* Guarded by media query, not by `phoneShell`: the server renders the
            desktop shell, and a phone's first paint must already show the bar. */}
        <header className="flex items-center justify-between border-b border-border px-1 py-1 md:hidden short:flex">
          <button
            ref={menuRef}
            type="button"
            aria-label="Open menu"
            aria-expanded={drawerOpen}
            onClick={() => setOpen(true)}
            className="flex size-12 items-center justify-center rounded-control text-ink"
          >
            <svg
              aria-hidden="true"
              width={20}
              height={20}
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
            >
              <path d="M3 5h14M3 10h14M3 15h14" />
            </svg>
          </button>
          <Link
            href="/chat"
            onClick={startNewChat}
            aria-label="Hax home"
            className="text-ink"
          >
            <Wordmark height={20} />
          </Link>
          <Link
            href="/chat"
            onClick={startNewChat}
            aria-label="New chat"
            className="flex size-12 items-center justify-center rounded-control text-ink"
          >
            <svg
              aria-hidden="true"
              width={20}
              height={20}
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
            >
              <path d="M10 3v14M3 10h14" />
            </svg>
          </Link>
        </header>
        <main className="min-h-0 min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
