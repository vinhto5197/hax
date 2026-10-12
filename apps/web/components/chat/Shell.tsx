"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { useConversations } from "@/components/chat/ConversationsProvider";
import { Sidebar } from "@/components/chat/Sidebar";
import { Wordmark } from "@/components/Wordmark";
import { SHOW_DOCUMENT_EVENT, revealDocumentRow } from "@/lib/showInPanel";

const DESKTOP = "(min-width: 768px)";
const REVEAL_POLL_MS = 100;
const REVEAL_TIMEOUT_MS = 2000;

// The server cannot know the viewport, so it renders the desktop shell; the
// static column is also CSS-hidden below `md`, which keeps a phone's first
// paint free of the sidebar until the client measures and unmounts it.
function useIsDesktop(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia(DESKTOP);
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    },
    () => window.matchMedia(DESKTOP).matches,
    () => true,
  );
}

// The shell owns the drawer, which exists only below `md`. The sidebar is
// mounted once at a time: in the static column on desktop, in the drawer on a
// phone while it is open, nowhere while it is closed. "Show in panel" and the
// documents poll depend on that single mount. The drawer closes on navigation
// so a tap on a conversation does not leave it covering the page.
export function Shell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const isDesktop = useIsDesktop();
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
  const drawerOpen = open && !isDesktop;
  if (open && isDesktop) setOpen(false);

  // "Show in panel" (lib/showInPanel.ts): with the sidebar in the static
  // column the row is revealed at once; on a phone it is not mounted, so the
  // id waits for the drawer to open.
  useEffect(() => {
    function onShowDocument(event: Event) {
      const { documentId } = (event as CustomEvent<{ documentId: string }>)
        .detail;
      if (isDesktop) {
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
      // A request made on one side of `md` does not carry to the other.
      pendingDocRef.current = null;
    };
  }, [isDesktop]);

  useEffect(() => {
    if (!drawerOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Focus follows the dialog in, and returns to the control that opened it.
    const opener = openerRef.current ?? menuRef.current;
    openerRef.current = null;
    panelRef.current?.focus();
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
      opener?.focus();
    };
  }, [drawerOpen]);

  const close = () => setOpen(false);

  return (
    <div className="flex h-dvh">
      {isDesktop ? (
        <div className="hidden w-72 shrink-0 md:block">
          <Sidebar />
        </div>
      ) : null}
      {drawerOpen ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            type="button"
            aria-label="Close menu"
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
        <header className="flex items-center justify-between border-b border-border px-1 py-1 md:hidden">
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
            aria-label="hax home"
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
