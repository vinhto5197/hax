"use client";

import { useSyncExternalStore } from "react";

// These must match Tailwind's `md` and the `short` custom variant in
// globals.css, in the unit each is declared in there (rem and px).
export const DESKTOP = "(min-width: 48rem)";
export const SHORT = "(max-height: 500px)";

type Subscribe = (onChange: () => void) => () => void;

// One subscribe function per query for the module's lifetime:
// useSyncExternalStore resubscribes whenever it is handed a new function, so
// an inline arrow would detach and reattach the listener on every render.
const subscribers = new Map<string, Subscribe>();

function subscribeTo(query: string): Subscribe {
  let subscribe = subscribers.get(query);
  if (!subscribe) {
    subscribe = (onChange) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    };
    subscribers.set(query, subscribe);
  }
  return subscribe;
}

// The server cannot see the viewport: it renders `serverValue`, and the
// client corrects after hydration.
export function useMediaQuery(query: string, serverValue: boolean): boolean {
  return useSyncExternalStore(
    subscribeTo(query),
    () => window.matchMedia(query).matches,
    () => serverValue,
  );
}
