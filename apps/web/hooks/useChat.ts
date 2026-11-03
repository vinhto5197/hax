"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  AlreadyAnsweredError,
  type ChatMessage,
  ConnectionLostError,
  type ConversationDetail,
  DemoLimitError,
  getConversation,
  NothingToRetryError,
  ReplyFailedError,
  ReplyRefusedError,
  type Source,
  stopReply,
  streamChat,
  streamRetry,
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

// What a run streams: a new question, or a new reply to the stored user
// message `after`. `hidden` is the reply to `after` the page showed when the
// retry was pressed (kept from a Stop), replaced by the new one; null when
// the page showed none.
type Turn =
  | { kind: "send"; prompt: string }
  | {
      kind: "retry";
      conversationId: string;
      after: string;
      hidden: ChatMessage | null;
    };

function toChatMessages(conv: ConversationDetail): ChatMessage[] {
  return conv.messages.map((m) => ({
    id: m.id,
    role: m.role,
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

// stopReply's bound fires as a TimeoutError: like a network failure, the stop
// may have reached the server.
function isStopNetworkFailure(err: unknown): boolean {
  return (
    isNetworkFailure(err) ||
    (typeof err === "object" &&
      err !== null &&
      (err as { name?: unknown }).name === "TimeoutError")
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
  // Asks the server to stop the reply this page is streaming; the stream's
  // own end then says what was kept.
  stop: () => Promise<void>;
  // After this send's prelude, while this page reads the stream and no stop
  // request is in flight; never while "Still answering…".
  canStop: boolean;
  // A stop this page sent ended its turn; live only (nothing is stored about
  // a stop), cleared by the next run and by a load.
  stoppedNotice: boolean;
  // Writes a new reply to the last user message, replacing the reply shown
  // after it, if any; the question is not sent again.
  retry: () => Promise<void>;
  // On "The reply was interrupted." or the stopped line, with a known
  // conversation and a stored last question, while nothing is busy.
  canRetry: boolean;
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
  // This send's prelude has arrived and its stream is still being read: the
  // turn is registered on the server, so a stop can find it.
  const [streaming, setStreaming] = useState(false);
  // A stop request in flight. The composer stays busy until it settles, so a
  // slow stop can never land on the user's next turn.
  const [stopping, setStopping] = useState(false);
  const [stoppedNotice, setStoppedNotice] = useState(false);
  // Set by Stop, reset by the next send, cleared when the server answered the
  // stop with an error status (it did not stop it). While set, a reply that
  // ends without text is the user's own doing: no "interrupted" line.
  const stoppedRef = useRef(false);
  // A send in this tab owns the outcome of its turn until it settles: a load
  // landing meanwhile neither starts "Still answering…" nor reports an
  // interruption.
  const sendingRef = useRef(false);
  const pollRef = useRef<Poll | null>(null);
  // The thread as last rendered, for a stop request that fails after its
  // turn has settled.
  const messagesRef = useRef(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);
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

  // A re-read that finds the conversation free decides the outcome: the
  // thread becomes the server's, and a last word that is the user's is an
  // interrupted reply, unless this page stopped it.
  const settleFree = useCallback((conv: ConversationDetail): boolean => {
    if (conv.replying) return false;
    setMessages(toChatMessages(conv));
    sendingRef.current = false;
    setStillAnswering(false);
    setIsLoading(false);
    if (stoppedRef.current) setStoppedNotice(true);
    else if (endsWithUser(conv)) setError(REPLY_FAILED);
    if (!endsWithUser(conv)) onTurnCompleteRef.current?.();
    return true;
  }, []);

  // Load history when the route's conversation changes. A new chat (null)
  // starts empty by construction — the session is keyed per conversation, so
  // it is always a fresh mount — and must NOT be cleared here: an effect can
  // run twice on mount (strict mode), and a second clear would wipe the
  // optimistic first turn a mount-send had placed.
  useEffect(() => {
    setActiveId(conversationId);
    setStoppedNotice(false);
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
          startPolling(conversationId, settleFree);
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
  }, [conversationId, startPolling, settleFree]);

  const busy = isLoading || stopping;

  // One turn's request and its outcome, from the optimistic user turn (a
  // send) or the hidden reply (a retry) to the settle (stream handlers,
  // refusals, failures, the poll after a lost connection, the final commit).
  // Every turn this page streams runs here.
  const runTurn = useCallback(
    async (turn: Turn): Promise<void> => {
      sendingRef.current = true;
      stoppedRef.current = false;
      setStoppedNotice(false);
      const generation = generationRef.current;
      // This send's user message id: whether the send reached the server is
      // asked by this id alone, never by text or time.
      const messageId = turn.kind === "send" ? crypto.randomUUID() : null;
      setRestoreDraft(null);

      // Kept by identity: a refusal removes exactly this turn, never "the last
      // message" — a history load landing mid-send replaces the list.
      const optimistic: ChatMessage | null =
        turn.kind === "send"
          ? {
              id: messageId ?? undefined,
              role: "user",
              content: turn.prompt,
              created_at: new Date().toISOString(),
            }
          : null;
      if (optimistic) setMessages((prev) => [...prev, optimistic]);
      // Removed by identity (a reply committed from the stream has no id).
      // Put back only on a refusal that deleted nothing (403 demo limit, 404);
      // after the prelude the server has deleted it, and any other outcome
      // re-reads the conversation.
      const hidden = turn.kind === "retry" ? turn.hidden : null;
      let restorable = hidden !== null;
      if (hidden) setMessages((prev) => prev.filter((m) => m !== hidden));
      const restoreHidden = () => {
        if (!hidden || !restorable || turn.kind !== "retry") return;
        restorable = false;
        setMessages((prev) => {
          if (prev.includes(hidden)) return prev;
          const at = prev.findIndex((m) => m.id === turn.after);
          if (at < 0) return prev;
          return [...prev.slice(0, at + 1), hidden, ...prev.slice(at + 1)];
        });
      };
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
      // A retry's thread as the server holds it after [DONE]; shown instead
      // of the streamed reply (another tab may have changed the conversation).
      let reread: ConversationDetail | null = null;

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
            if (turn.kind === "send") setRestoreDraft(turn.prompt);
            return true;
          }
          setMessages(toChatMessages(conv));
          if (stoppedRef.current) setStoppedNotice(true);
          else if (endsWithUser(conv)) setError(REPLY_FAILED);
          onTurnCompleteRef.current?.();
          return true;
        });
        return true;
      };

      // A retry's outcome read from the conversation, settled as a load's
      // poll. `confirm`: an interrupted reply only after two consecutive free
      // reads, for a request that may still claim the conversation.
      const pollForRetry = (id: string, confirm: boolean): boolean => {
        if (generationRef.current !== generation) return false;
        setStillAnswering(true);
        let misses = 0;
        startPolling(id, (conv) => {
          if (conv.replying) {
            misses = 0;
            return false;
          }
          if (confirm && endsWithUser(conv) && ++misses < 2) return false;
          return settleFree(conv);
        });
        return true;
      };

      const handlers = {
        onConversationId: (id: string) => {
          learnedId = id;
          // Set-once: a late prelude can't overwrite activeId after we've
          // navigated elsewhere (which would misroute the next send).
          setActiveId((current) => current ?? id);
          setStreaming(true);
          if (turn.kind === "retry") {
            // The retry holds the claim: the replaced reply is deleted.
            restorable = false;
            return;
          }
          // Only fires on a new chat's first turn (activeId null only then).
          if (!activeId) onConversationCreated?.(id);
          // The prelude follows the saved user turn, which moved an
          // existing conversation to the top of the list.
          else onTurnStarted?.();
        },
        onChunk: (chunk: string) => {
          fullContent += chunk;
          setStreamingContent(fullContent);
          // Text arriving means the announced tool has finished.
          setStatus(null);
        },
        onStatus: setStatus,
        onSources: (batch: Source[]) => {
          for (const s of batch) {
            const key = `${s.document_id}:${s.chunk_idx}`;
            if (!sources.has(key)) sources.set(key, s);
          }
        },
      };

      try {
        if (turn.kind === "send") {
          await streamChat(turn.prompt, activeId, handlers, model, messageId);
        } else {
          await streamRetry(
            turn.conversationId,
            turn.after,
            hidden !== null,
            handlers,
            model,
          );
          setStreaming(false);
          try {
            const conv = await getConversation(turn.conversationId);
            if (generationRef.current === generation) reread = conv;
          } catch {
            // The streamed reply stays shown.
          }
        }

        if (stoppedRef.current) setStoppedNotice(true);
        onTurnComplete?.();
      } catch (err) {
        if (err instanceof DemoLimitError) {
          // Refused before anything was persisted: drop the optimistic turn
          // so the view matches the server.
          setMessages((prev) => prev.filter((m) => m !== optimistic));
          restoreHidden();
          setLimited(true);
          return;
        }
        if (
          turn.kind === "retry" &&
          (err instanceof NothingToRetryError ||
            err instanceof AlreadyAnsweredError)
        ) {
          // Refused before anything changed: the conversation moved on, so
          // show it as it is now.
          try {
            const conv = await getConversation(turn.conversationId);
            if (generationRef.current !== generation) return;
            if (settleFree(conv)) return;
          } catch {
            // The poll below reads it again.
          }
          polling = pollForRetry(turn.conversationId, false);
          return;
        }
        if (err instanceof TurnInProgressError) {
          if (turn.kind === "retry") {
            // Another reply holds the conversation: show it once saved.
            polling = pollForRetry(turn.conversationId, false);
            return;
          }
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
          if (stoppedRef.current) setStoppedNotice(true);
          else setError(REPLY_FAILED);
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
            polling =
              turn.kind === "send"
                ? pollForOutcome(id)
                : pollForRetry(id, false);
            return;
          }
          // A first turn cut before its prelude: no id to watch. The
          // sidebar lists the new conversation, its reply once saved.
          setError(REPLY_FAILED);
          onTurnComplete?.();
          return;
        }
        if (activeId && learnedId === null && isNetworkFailure(err)) {
          // No response at all: whether the message arrived (a send) or the
          // retry claimed the conversation is learned from the conversation
          // itself.
          polling =
            turn.kind === "send"
              ? pollForOutcome(activeId)
              : pollForRetry(activeId, true);
          return;
        }
        if (turn.kind === "retry") {
          // A 404 deleted nothing. Any other status may follow the claim's
          // committed delete (a failure before the prelude): show what the
          // server holds.
          if (err instanceof ReplyRefusedError && err.status === 404) {
            restoreHidden();
          } else if (err instanceof ReplyRefusedError) {
            polling = pollForRetry(turn.conversationId, true);
            return;
          }
        }
        const errMessage =
          err instanceof Error ? err.message : "Unable to get response.";
        setError(errMessage);
      } finally {
        // Commit whatever streamed — on success AND any error but a model
        // failure or a lost connection, which clear it. Then clear the
        // streaming buffer or the text would render twice.
        if (reread) {
          setMessages(toChatMessages(reread));
        } else if (fullContent) {
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
        setStreaming(false);
        setStreamingContent("");
        setStatus(null);
      }
    },
    [
      model,
      activeId,
      onConversationCreated,
      onTurnComplete,
      onTurnStarted,
      startPolling,
      settleFree,
    ],
  );

  const send = useCallback(
    async (text: string): Promise<void> => {
      const prompt = text.trim();
      if (!prompt || busy) return;
      await runTurn({ kind: "send", prompt });
    },
    [busy, runTurn],
  );

  const lastUserAt = messages.findLastIndex((m) => m.role === "user");
  const after = messages[lastUserAt]?.id ?? null;
  const canRetry =
    activeId !== null &&
    after !== null &&
    !busy &&
    (error === REPLY_FAILED || stoppedNotice);

  // `after` and the reply it replaces are read from the thread as shown
  // now: the server deletes a reply only when the page showed one.
  const retry = useCallback(async (): Promise<void> => {
    if (!canRetry || activeId === null || after === null) return;
    const next = messages[lastUserAt + 1];
    const hidden = next?.role === "assistant" ? next : null;
    await runTurn({ kind: "retry", conversationId: activeId, after, hidden });
  }, [canRetry, activeId, after, messages, lastUserAt, runTurn]);

  const canStop = streaming && !stopping && !stillAnswering;

  // Targets activeId, which the prelude set in the same update that made
  // canStop true; never a send closure's id.
  const stop = useCallback(async (): Promise<void> => {
    if (!canStop || !activeId) return;
    stoppedRef.current = true;
    setStopping(true);
    try {
      await stopReply(activeId);
    } catch (err) {
      // An error status: the server did not stop it, so a later failure must
      // show. A network failure keeps it set: that stop may have landed.
      if (!isStopNetworkFailure(err)) {
        stoppedRef.current = false;
        // The turn settled first, as a stopped one: undo that.
        if (!sendingRef.current) {
          setStoppedNotice(false);
          if (messagesRef.current.at(-1)?.role === "user") {
            setError(REPLY_FAILED);
          }
        }
      }
    } finally {
      setStopping(false);
    }
  }, [canStop, activeId]);

  return {
    messages,
    isLoading: busy,
    streamingContent,
    status,
    error,
    limited,
    stillAnswering,
    restoreDraft,
    send,
    stop,
    canStop,
    stoppedNotice,
    retry,
    canRetry,
  };
}
