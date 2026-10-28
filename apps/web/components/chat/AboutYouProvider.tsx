"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import type { Session } from "next-auth";
import { getSession, useSession } from "next-auth/react";

import { AboutYouDialog } from "@/components/chat/AboutYouDialog";

type AboutYou = { open: () => void };

const AboutYouContext = createContext<AboutYou | null>(null);

// Null outside the provider: the account menu leaves out its About you item
// there.
export function useAboutYou(): AboutYou | null {
  return useContext(AboutYouContext);
}

function memberOf(session: Session | null): string | null {
  return session?.user?.id ?? session?.user?.email ?? null;
}

// Holds only whether the dialog is open, and renders the dialog itself: it
// sits above the sidebar (mounted in the chat layout), so a route change or a
// sidebar swapped across the breakpoint never unmounts the dialog and the
// text typed into it.
export function AboutYouProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const { data: session } = useSession();
  const member = memberOf(session);

  // Another tab signing in as someone else swaps the session under this one;
  // the open dialog closes so one member's text is never saved under another's
  // session. A transient null (a sign-out, a refetch) is not a change of
  // member. Adjusted during render so the stale dialog never paints.
  const [seenMember, setSeenMember] = useState(member);
  if (member !== null && member !== seenMember) {
    setSeenMember(member);
    if (seenMember !== null) setIsOpen(false);
  }

  // useSession lags the cookie by a refetch, so the check above can miss a
  // switch made just before Save; the save asks the server whose cookie the
  // browser holds now and goes out only if it is still the same member.
  const confirmMember = useCallback(
    async () => memberOf(await getSession()) === seenMember,
    [seenMember],
  );

  const value = useMemo(() => ({ open: () => setIsOpen(true) }), []);

  return (
    <AboutYouContext.Provider value={value}>
      {children}
      {isOpen ? (
        <AboutYouDialog
          onClose={() => setIsOpen(false)}
          confirmMember={confirmMember}
        />
      ) : null}
    </AboutYouContext.Provider>
  );
}
