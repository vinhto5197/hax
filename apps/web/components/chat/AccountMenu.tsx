"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { signOut } from "next-auth/react";

import { useAboutYou } from "@/components/chat/AboutYouProvider";

const ITEM =
  "block w-full px-3 py-2 text-left text-body text-ink hover:bg-surface-2";

// The account row as a button opening a menu above it. Escape is handled by
// React's onKeyDown and marked defaultPrevented, so Shell's document-level
// listener leaves the phone drawer open (React's listener on the document runs
// first; a document listener of this component's own would run after Shell's).
export function AccountMenu({
  name,
  email,
  onNavigate,
}: {
  name: string;
  email: string;
  onNavigate?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const aboutYou = useAboutYou();

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key !== "Escape" || !open) return;
    event.preventDefault();
    setOpen(false);
    buttonRef.current?.focus();
  }

  return (
    <div
      ref={rootRef}
      onKeyDown={onKeyDown}
      className="relative border-t border-border pt-3"
    >
      {open ? (
        <div
          role="menu"
          aria-label="Account"
          className="absolute inset-x-0 bottom-full mb-1 overflow-hidden rounded-card border border-border bg-surface-1 py-1 shadow-lg"
        >
          {aboutYou ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                aboutYou.open();
              }}
              className={ITEM}
            >
              About you
            </button>
          ) : null}
          <Link
            href="/privacy"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onNavigate?.();
            }}
            className={ITEM}
          >
            Privacy
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={() => signOut({ callbackUrl: "/" })}
            className={ITEM}
          >
            Sign out
          </button>
        </div>
      ) : null}
      <button
        ref={buttonRef}
        type="button"
        aria-label="Account menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="block w-full min-w-0 rounded-control px-1 py-1 text-left hover:bg-surface-2"
      >
        <span
          className="block truncate text-body font-medium text-ink"
          title={name}
        >
          {name}
        </span>
        {name !== email ? (
          <span className="block truncate text-small text-ink-3" title={email}>
            {email}
          </span>
        ) : null}
      </button>
    </div>
  );
}
