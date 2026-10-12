import Link from "next/link";

import { Wordmark } from "@/components/Wordmark";

// Pages without the chat shell (auth screens, privacy) carry this header; the
// landing has its own, with the sign-in links.
export function PublicHeader() {
  return (
    <header className="flex justify-center px-4 py-4">
      <Link href="/" aria-label="hax home" className="text-ink">
        <Wordmark />
      </Link>
    </header>
  );
}
