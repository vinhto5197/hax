"use client";

import { useEffect } from "react";

// sessionStorage, not memory: the reload discards the module, and the guard
// must survive it to stop a reload loop when the new build is still missing.
const CHUNK_RELOAD_KEY = "hax:chunk-reload";

const CHUNK_MESSAGE =
  /Loading chunk|Failed to fetch dynamically imported module/;

// A tab that still runs the previous build asks for route chunks the deploy
// has replaced; a full reload fetches the new build.
function isChunkLoadError(error: Error): boolean {
  return error.name === "ChunkLoadError" || CHUNK_MESSAGE.test(error.message);
}

function readGuard(): boolean {
  try {
    return sessionStorage.getItem(CHUNK_RELOAD_KEY) !== null;
  } catch {
    return false;
  }
}

// Storage can throw (private mode, blocked site data); without it the guard
// cannot hold, so the card is shown instead of risking a reload loop.
function writeGuard(): boolean {
  try {
    sessionStorage.setItem(CHUNK_RELOAD_KEY, "1");
    return true;
  } catch {
    return false;
  }
}

// One decision per error object, so a second render of the same error (Strict
// Mode, a parent update) reads the decision instead of the guard it has just
// written. true = reload.
const decisions = new WeakMap<Error, boolean>();

function decideReload(error: Error): boolean {
  let reload = decisions.get(error);
  if (reload === undefined) {
    reload = !readGuard() && writeGuard();
    decisions.set(error, reload);
  }
  return reload;
}

function clearGuard(): void {
  try {
    sessionStorage.removeItem(CHUNK_RELOAD_KEY);
  } catch {
    // Nothing to clear.
  }
}

// The App Router's boundary for every route below the root layout. A chunk
// error reloads the page once; with the guard already set (the reload did
// not help) it shows the card and clears the guard, so a later failure, after
// Retry or the next deploy, may reload once again.
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const chunk = isChunkLoadError(error);
  const reloading = chunk && decideReload(error);

  useEffect(() => {
    if (reloading) window.location.reload();
    else if (chunk) clearGuard();
  }, [reloading, chunk]);

  if (reloading) return null;

  return (
    <div className="flex h-full items-center justify-center p-4">
      <div
        role="alert"
        className="flex max-w-sm flex-col items-center gap-3 rounded-card border border-border bg-surface-1 p-6 text-center"
      >
        <p className="text-body text-ink">Something went wrong</p>
        <button
          type="button"
          onClick={reset}
          className="rounded-control border border-border-control px-3 py-1 text-small text-ink hover:bg-surface-2"
        >
          Retry
        </button>
      </div>
    </div>
  );
}
