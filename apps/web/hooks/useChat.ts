"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type ChatMessage,
  ConnectionLostError,
  type ConversationDetail,
  DemoLimitError,
  getConversation,
  ReplyFailedError,
  type Source,
  streamChat,
  TurnInProgressError,
} from "@/lib/chatApi";

// No resend advice: a failure that repeats (a conversation past the model's
// context) would fail again.
const REPLY_FAILED = "The reply was interrupted.";
const NOT_SENT =
  "Your message wasn't sent. Check your connection and try again.";
const TAKING_LONGER =
  "This reply is taking longer than usual. Reload to check on it.";

// While a reply runs on the server without this tab listening, the
// conversation is re-read this often until it is no longer `replying`.
const POLL_INTERVAL_MS = 2_000;
// Past the server's 10-minute turn deadline, and a dead server process frees
// the conversation within 2 minutes: reaching this means a bug, not a slow
// reply.
const POLL_CAP_MS = 12 * 60_000;

type Poll = {
  stop: () => void;
};

function toChatMessages(conv: ConversationDetail): ChatMessage[] {
  // role is `string` in the generated type but constrained to user/assistant
  // by a DB CHECK; safe to narrow.
  return conv.messages.map((m) => ({
    role: m.role as ChatMessage["role"],
    content: m.content,
    // null (user rows, sourceless turns) and undefined both mean no footer.
    sources: m.sources ?? undefined,
    created_at: m.created_at,
  }));
}

function endsWithUser(conv: ConversationDetail): boolean {
  return conv.messages.at(-1)?.role === "user";
}

// fetch's own rejection (offline, DNS, or the silence limit's abort): the
// request may or may not have reached the server.
function isNetworkFailure(err: unknown): boolean {
  if (err instanceof TypeError) return true;
  return (
    typeof err === "object" &&
    err !== null &&
    (err as { name?: unknown }).name === "AbortError"
  );
}

type UseChatResult = {
  messages: ChatMessage[];
  isLoading: boolean;
  streamingContent: string;
  // Live tool-activity note from the agentic harness ("Searching documents…"),
  // or null when no tool is running. Transient — never part of the transcript.
  status: string | null;
  error: string | null;
  // An anonymous visitor hit the demo cap; the caller shows the sign-up prompt.
  limited: boolean;
  // A reply is running on the server that this tab is not streaming (loaded
  // mid-reply, or the connection was lost): the thread shows "Still
  // answering…", isLoading stays true, and the conversation is re-read every
  // POLL_INTERVAL_MS until the reply is saved or has failed.
  stillAnswering: boolean;
  // The text of a send that never reached the server, for the composer;
  // null otherwise.
  restoreDraft: string | null;
  send: (text: string) => Promise<void>;
};

// Owns all chat state for the current conversation: transcript, streaming
// buffer, tool status, loading/error, and send. Optional callbacks report
// lazy-create, a saved user turn and turn-completion so the hook stays
// decoupled from routing/sidebar concerns. `model` null -> server default
// (env LLM_MODEL).
export function useChat(
  conversationId: string | null,
  model: string | null,
  onConversationCreated?: (id: string) => void,
  onTurnComplete?: () => void,
  onTurnStarted?: () => void,
): UseChatResult {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [limited, setLimited] = useState(false);
  // The id sends target. Starts from the route prop; updated when a lazy-create
  // returns a new id, so follow-up turns hit the same conversation even though
  // the route prop stayed null (the URL was updated shallowly, not navigated).
  const [activeId, setActiveId] = useState<string | null>(conversationId);
  const [stillAnswering, setStillAnswering] = useState(false);
  const [restoreDraft, setRestoreDraft] = useState<string | null>(null);
  // A send in this tab owns the outcome of its turn until it settles: a load
  // landing meanwhile neither starts "Still answering…" nor reports an
  // interruption.
  const sendingRef = useRef(false);
  const pollRef = useRef<Poll | null>(null);
  // Bumped when the conversation changes or the hook unmounts: a send that
  // ends after that must not start polling.
  const generationRef = useRef(0);
  const onTurnCompleteRef = useRef(onTurnComplete);
  useEffect(() => {
    onTurnCompleteRef.current = onTurnComplete;
  }, [onTurnComplete]);

  // At most one poll at a time. `settle` sees every successful re-read and
  // returns true once it has decided the outcome, which ends the polling; a
  // failed re-read is retried on the next tick, unshown.
  const startPolling = useCallback(
    (id: string, settle: (conv: ConversationDetail) => boolean) => {
      pollRef.current?.stop();
      let stopped = false;
      let tick: ReturnType<typeof setTimeout> | undefined;
      const poll: Poll = {
        stop: () => {
          stopped = true;
          clearTimeout(tick);
          clearTimeout(cap);
          if (pollRef.current === poll) pollRef.current = null;
        },
      };
      const cap = setTimeout(() => {
        poll.stop();
        sendingRef.current = false;
        setStillAnswering(false);
        setIsLoading(false);
        setError(TAKING_LONGER);
      }, POLL_CAP_MS);
      const check = async () => {
        try {
          const conv = await getConversation(id);
          if (stopped) return;
          if (settle(conv)) {
            poll.stop();
            return;
          }
        } catch {
          // Retried on the next tick.
        }
        if (!stopped) tick = setTimeout(check, POLL_INTERVAL_MS);
      };
      tick = setTimeout(check, POLL_INTERVAL_MS);
      pollRef.current = poll;
    },
    [],
  );

  // Load history when the route's conversation changes. A new chat (null)
  // starts empty by construction — the session is keyed per conversation, so
  // it is always a fresh mount — and must NOT be cleared here: an effect can
  // run twice on mount (strict mode), and a second clear would wipe the
  // optimistic first turn a mount-send had placed.
  useEffect(() => {
    setActiveId(conversationId);
    const generation = generationRef.current;
    // Polling belongs to the conversation it watches.
    const stopPolling = () => {
      generationRef.current = generation + 1;
      if (!pollRef.current) return;
      pollRef.current.stop();
      sendingRef.current = false;
      setStillAnswering(false);
      setIsLoading(false);
    };
    if (!conversationId) return stopPolling;
    // Race guard: each run owns this flag; cleanup flips it on navigation so a
    // slower earlier fetch can't overwrite the conversation we moved to.
    let cancelled = false;
    getConversation(conversationId)
      .then((conv) => {
        if (cancelled) return;
        setMessages(toChatMessages(conv));
        if (sendingRef.current) return;
        if (conv.replying) {
          setStillAnswering(true);
          setIsLoading(true);
          startPolling(conversationId, (settled) => {
            if (settled.replying) return false;
            setMessages(toChatMessages(settled));
            setStillAnswering(false);
            setIsLoading(false);
            if (endsWithUser(settled)) setError(REPLY_FAILED);
            else onTurnCompleteRef.current?.();
            return true;
          });
        } else if (endsWithUser(conv)) {
          // Free, and the last word is the user's: its reply failed or was
          // cut by a deploy, here or in another tab, now or long ago.
          setError(REPLY_FAILED);
        }
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load this conversation.");
      });
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [conversationId, startPolling]);

  const send = useCallback(
    async (text: string): Promise<void> => {
      const prompt = text.trim();
      if (!prompt || isLoading) return;
      sendingRef.current = true;
      const generation = generationRef.current;
      // This send's user message id: whether the send reached the server is
      // asked by this id alone, never by text or time.
      const messageId = crypto.randomUUID();
      setRestoreDraft(null);

      // Kept by identity: a refusal removes exactly this turn, never "the last
      // message" — a history load landing mid-send replaces the list.
      const optimistic: ChatMessage = {
        role: "user",
        content: prompt,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimistic]);
      setIsLoading(true);
      setStreamingContent("");
      setError(null);

      // Source of truth for the final assistant message. streamingContent
      // (state) mirrors this for live rendering, but state is async/batched —
      // fullContent accumulates synchronously so the finally can commit it.
      let fullContent = "";
      // Provenance for this turn. The server dedups only what it persists
      // and forwards every event unchanged, so two searches that hit the
      // same chunk arrive twice here; dedup by the server's key, first-seen
      // order, so the live turn's sources match the reloaded ones.
      const sources = new Map<string, Source>();
      // The id this send learned from the prelude: on a first turn activeId
      // is still null in this closure.
      let learnedId: string | null = null;
      // Set when the turn's outcome is handed to a poll, which then owns
      // isLoading and sendingRef.
      let polling = false;

      // Watch the conversation until the reply is saved or has failed, then
      // decide whether this send's message reached the server at all. Not
      // sent only after two consecutive free reads without its id: a request
      // still in flight can store the message just after the first read.
      const pollForOutcome = (id: string): boolean => {
        if (generationRef.current !== generation) return false;
        setStillAnswering(true);
        let misses = 0;
        startPolling(id, (conv) => {
          if (conv.replying) {
            misses = 0;
            return false;
          }
          const arrived = conv.messages.some((m) => m.id === messageId);
          if (!arrived && ++misses < 2) return false;
          sendingRef.current = false;
          setStillAnswering(false);
          setIsLoading(false);
          if (!arrived) {
            setMessages((prev) => prev.filter((m) => m !== optimistic));
            setError(NOT_SENT);
            setRestoreDraft(prompt);
            return true;
          }
          setMessages(toChatMessages(conv));
          if (endsWithUser(conv)) setError(REPLY_FAILED);
          onTurnCompleteRef.current?.();
          return true;
        });
        return true;
      };

      try {
        await streamChat(
          prompt,
          activeId,
          {
            onConversationId: (id) => {
              learnedId = id;
              // Set-once: a late prelude can't overwrite activeId after we've
              // navigated elsewhere (which would misroute the next send).
              setActiveId((current) => current ?? id);
              // Only fires on a new chat's first turn (activeId null only then).
              if (!activeId) onConversationCreated?.(id);
              // The prelude follows the saved user turn, which moved an
              // existing conversation to the top of the list.
              else onTurnStarted?.();
            },
            onChunk: (chunk) => {
              fullContent += chunk;
              setStreamingContent(fullContent);
              // Text arriving means the announced tool has finished.
              setStatus(null);
            },
            onStatus: setStatus,
            onSources: (batch) => {
              for (const s of batch) {
                const key = `${s.document_id}:${s.chunk_idx}`;
                if (!sources.has(key)) sources.set(key, s);
              }
            },
          },
          model,
          messageId,
        );

        onTurnComplete?.();
      } catch (err) {
        if (err instanceof DemoLimitError) {
          // Refused before anything was persisted: drop the optimistic turn
          // so the view matches the server.
          setMessages((prev) => prev.filter((m) => m !== optimistic));
          setLimited(true);
          return;
        }
        if (err instanceof TurnInProgressError) {
          // Also refused before anything was persisted (another reply is
          // running in this conversation): drop the optimistic turn.
          setMessages((prev) => prev.filter((m) => m !== optimistic));
          setError(err.message);
          return;
        }
        if (err instanceof ReplyFailedError) {
          // The server stored no reply: drop the partial so the view matches
          // it. The user's turn was saved and stays.
          fullContent = "";
          setError(REPLY_FAILED);
          return;
        }
        if (err instanceof ConnectionLostError) {
          // The reply runs on in the server and is saved whole or not at
          // all; a frozen partial would read as finished.
          fullContent = "";
          setStreamingContent("");
          setStatus(null);
          const id = activeId ?? learnedId;
          if (id) {
            polling = pollForOutcome(id);
            return;
          }
          // A first turn cut before its prelude: no id to watch. The
          // sidebar lists the new conversation, its reply once saved.
          setError(REPLY_FAILED);
          onTurnComplete?.();
          return;
        }
        if (activeId && learnedId === null && isNetworkFailure(err)) {
          // No response at all: whether the message arrived is learned from
          // the conversation itself.
          polling = pollForOutcome(activeId);
          return;
        }
        const errMessage =
          err instanceof Error ? err.message : "Unable to get response.";
        setError(errMessage);
      } finally {
        // Commit whatever streamed — on success AND any error but a model
        // failure or a lost connection, which clear it. Then clear the
        // streaming buffer or the text would render twice.
        if (fullContent) {
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              content: fullContent,
              sources: sources.size ? [...sources.values()] : undefined,
              created_at: new Date().toISOString(),
            },
          ]);
        }
        if (!polling) {
          sendingRef.current = false;
          setIsLoading(false);
        }
        setStreamingContent("");
        setStatus(null);
      }
    },
    [
      isLoading,
      model,
      activeId,
      onConversationCreated,
      onTurnComplete,
      onTurnStarted,
      startPolling,
    ],
  );

  return {
    messages,
    isLoading,
    streamingContent,
    status,
    error,
    limited,
    stillAnswering,
    restoreDraft,
    send,
  };
}
