"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { signOut, useSession } from "next-auth/react";

import { useConversations } from "@/components/chat/ConversationsProvider";
import { DocumentsPanel } from "@/components/chat/DocumentsPanel";
import { Wordmark } from "@/components/Wordmark";
import { type ConversationSummary, deleteConversation } from "@/lib/chatApi";
import { formatRelative } from "@/lib/time";

export function Sidebar() {
  // Shared list from context (see ConversationsProvider), not a prop.
  const { conversations, startNewChat, refresh } = useConversations();
  const { data: session } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Sticky, never cleared: SessionProvider broadcasts a sign-out from another
  // tab, so the live session can flip to null under a still-mounted shell.
  // Rendering off the live value would unmount just this block and leave the
  // shell half-dissolved. Eviction is owned elsewhere — apiFetch's 401 handler
  // (lib/chatApi.ts) signs out and middleware redirects, as does a reload.
  const [account, setAccount] = useState<{
    email: string;
    name: string | null;
  } | null>(null);
  const liveEmail = session?.user?.email ?? null;
  const liveName = session?.user?.name ?? null;
  useEffect(() => {
    if (liveEmail) setAccount({ email: liveEmail, name: liveName });
  }, [liveEmail, liveName]);
  // A nameless account shows its email once, as the name line.
  const displayName = account?.name?.trim() || account?.email;

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
    <aside className="flex h-screen w-72 shrink-0 flex-col gap-3 border-r border-border p-3">
      <div className="flex items-center justify-between">
        <Link
          href="/chat"
          onClick={startNewChat}
          aria-label="hax home"
          className="text-ink"
        >
          <Wordmark />
        </Link>
        {/* startNewChat itself decides whether a nonce bump is needed (only when
            no real /chat/[id] is mounted — see ConversationsProvider). */}
        <Link
          href="/chat"
          onClick={startNewChat}
          className="rounded-control bg-accent px-3 py-1.5 text-body font-medium text-accent-ink"
        >
          + New chat
        </Link>
      </div>

      {error && <p className="px-1 text-small text-status-failed">{error}</p>}

      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <p className="px-1 py-2 text-body text-ink-3">
            No conversations yet. Start one above.
          </p>
        ) : (
          conversations.map((conversation) => {
            const active = pathname === `/chat/${conversation.id}`;
            return (
              // A row is a div, not a Link: the delete button can't nest inside
              // an anchor (invalid HTML; nested interactive elements).
              // ink-3 holds contrast on ground and surface-2 only, so the active
              // row (surface-3) steps its secondary text up to ink-2.
              <div
                key={conversation.id}
                className={`flex items-center rounded-control ${
                  active ? "bg-surface-3" : "hover:bg-surface-2"
                }`}
              >
                <Link
                  href={`/chat/${conversation.id}`}
                  className="min-w-0 flex-1 px-3 py-2 text-body"
                >
                  {/* Titling runs in the worker off the first user message and
                      can land mid-stream; until it does, the entry must read as
                      state, not as a name. */}
                  <span
                    className={`block truncate ${
                      conversation.title
                        ? active
                          ? "text-ink"
                          : "text-ink-2"
                        : `italic ${active ? "text-ink-2" : "text-ink-3"}`
                    }`}
                  >
                    {conversation.title ?? "Untitled"}
                  </span>
                  <span
                    className={`block text-small ${active ? "text-ink-2" : "text-ink-3"}`}
                  >
                    {formatRelative(conversation.updated_at)}
                  </span>
                </Link>
                <button
                  type="button"
                  onClick={() => handleDelete(conversation)}
                  disabled={deletingId === conversation.id}
                  aria-label={`Delete ${conversation.title ?? "conversation"}`}
                  className={`shrink-0 px-2 py-2 text-sm leading-none hover:text-status-failed disabled:opacity-50 ${active ? "text-ink-2" : "text-ink-3"}`}
                >
                  ×
                </button>
              </div>
            );
          })
        )}
      </nav>

      <DocumentsPanel />

      {account && (
        <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
          <div className="min-w-0">
            <p
              className="truncate text-body font-medium text-ink"
              title={displayName}
            >
              {displayName}
            </p>
            {displayName !== account.email ? (
              <p
                className="truncate text-small text-ink-3"
                title={account.email}
              >
                {account.email}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="shrink-0 text-body text-ink-2 hover:text-ink"
          >
            Sign out
          </button>
        </div>
      )}
    </aside>
  );
}
