"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useConversations } from "@/components/chat/ConversationsProvider";
import { DocumentsPanel } from "@/components/chat/DocumentsPanel";

export function Sidebar() {
  // Shared list from context (see ConversationsProvider), not a prop.
  const { conversations, startNewChat } = useConversations();
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-64 shrink-0 flex-col gap-3 border-r border-black/10 p-3 dark:border-white/10">
      {/* onClick bumps the session nonce: navigation alone can't reset a chat
          whose URL came from history.replaceState (same-route, no prop change). */}
      <Link
        href="/chat"
        onClick={startNewChat}
        className="rounded-md bg-foreground px-3 py-2 text-center text-sm text-background"
      >
        + New chat
      </Link>

      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <p className="px-1 py-2 text-xs text-black/50 dark:text-white/50">
            No conversations yet.
          </p>
        ) : (
          conversations.map((conversation) => {
            const active = pathname === `/chat/${conversation.id}`;
            return (
              <Link
                key={conversation.id}
                href={`/chat/${conversation.id}`}
                className={`truncate rounded-md px-3 py-2 text-sm ${
                  active
                    ? "bg-black/10 dark:bg-white/15"
                    : "text-black/70 hover:bg-black/5 dark:text-white/70 dark:hover:bg-white/10"
                }`}
              >
                {/* Titles are generated async (Slice 4); placeholder til then. */}
                {conversation.title ?? "New conversation"}
              </Link>
            );
          })
        )}
      </nav>

      <DocumentsPanel />
    </aside>
  );
}
