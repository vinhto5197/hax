"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { useConversations } from "@/components/chat/ConversationsProvider";
import { DocumentsPanel } from "@/components/chat/DocumentsPanel";
import { type ConversationSummary, deleteConversation } from "@/lib/chatApi";

export function Sidebar() {
  // Shared list from context (see ConversationsProvider), not a prop.
  const { conversations, startNewChat, refresh } = useConversations();
  const pathname = usePathname();
  const router = useRouter();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleDelete(conversation: ConversationSummary) {
    // Irreversible (drops the conversation + all its messages) — confirm first.
    const label = conversation.title ?? "this conversation";
    if (!window.confirm(`Delete "${label}"? This can't be undone.`)) return;
    setError(null);
    setDeletingId(conversation.id);
    try {
      await deleteConversation(conversation.id);
      if (pathname === `/chat/${conversation.id}`) {
        // Deleting the open conversation resets to a fresh chat. Two cases,
        // each a no-op in the other: a lazy-created conversation only has this
        // URL via history.replaceState (the router still thinks it's on /chat,
        // so push() won't remount — the nonce from startNewChat is the reset);
        // a real /chat/[id] remounts via push()'s prop change (no nonce bump —
        // startNewChat skips it when a routed id is reported).
        startNewChat();
        router.push("/chat");
      }
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <aside className="flex h-screen w-64 shrink-0 flex-col gap-3 border-r border-black/10 p-3 dark:border-white/10">
      {/* startNewChat itself decides whether a nonce bump is needed (only when
          no real /chat/[id] is mounted — see ConversationsProvider). */}
      <Link
        href="/chat"
        onClick={startNewChat}
        className="rounded-md bg-foreground px-3 py-2 text-center text-sm text-background"
      >
        + New chat
      </Link>

      {error && (
        <p className="px-1 text-xs text-red-600 dark:text-red-400">{error}</p>
      )}

      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <p className="px-1 py-2 text-xs text-black/50 dark:text-white/50">
            No conversations yet.
          </p>
        ) : (
          conversations.map((conversation) => {
            const active = pathname === `/chat/${conversation.id}`;
            return (
              // A row is a div, not a Link: the delete button can't nest inside
              // an anchor (invalid HTML; nested interactive elements).
              <div
                key={conversation.id}
                className={`flex items-center rounded-md ${
                  active
                    ? "bg-black/10 dark:bg-white/15"
                    : "hover:bg-black/5 dark:hover:bg-white/10"
                }`}
              >
                <Link
                  href={`/chat/${conversation.id}`}
                  className={`min-w-0 flex-1 truncate px-3 py-2 text-sm ${
                    active ? "" : "text-black/70 dark:text-white/70"
                  }`}
                >
                  {/* Titles are generated async (M2.5); placeholder til then. */}
                  {conversation.title ?? "New conversation"}
                </Link>
                <button
                  type="button"
                  onClick={() => handleDelete(conversation)}
                  disabled={deletingId === conversation.id}
                  aria-label={`Delete ${conversation.title ?? "conversation"}`}
                  className="shrink-0 px-2 py-2 text-sm leading-none text-black/30 hover:text-red-600 disabled:opacity-50 dark:text-white/30 dark:hover:text-red-400"
                >
                  ×
                </button>
              </div>
            );
          })
        )}
      </nav>

      <DocumentsPanel />
    </aside>
  );
}
