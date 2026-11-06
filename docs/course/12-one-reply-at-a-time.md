# 12. One reply at a time

Threads: A (agentic LLM systems) · B (full-stack engineering)

## The idea

A chat is a strict alternation: question, answer, question, answer. The model only sees the conversation as that list, so the order of saved messages is the model's memory. If two replies are written into one conversation at once, every later answer is built on a scrambled history.

Think of one microphone at a table: whoever holds it speaks, everyone else waits, and if the speaker walks out someone must take it back. In hax each conversation has one, called the claim.

## How hax does it

The claim is a timestamp column, `conversations.streaming_since`. When a user sends a message, one conditional UPDATE (a database write that happens only if a stated condition holds) sets it to the database's current time, but only if it is empty or older than two minutes (`TURN_WINDOW` in [`packages/db/repos/conversations.py`](../../packages/db/repos/conversations.py)). That update runs in the same transaction (a group of database steps that succeed or fail together) that checks ownership and saves the user's message. If another reply holds a live claim, the request gets 409 (the HTTP, or web request, status code for "conflicts with the current state") before anything is stored.

The reply itself runs in [`apps/api/turns.py`](../../apps/api/turns.py) as an asyncio task (work the Python server runs alongside others, independent of any request). The route claims the turn, starts the task, and returns the stream. The request only listens: it forwards the task's events to the browser over SSE (server-sent events: one open connection the server writes the reply into piece by piece) and ends with `[DONE]` or a `reply_failed` frame. If the tab closes, the listener detaches and the task carries on.

While the task runs, a heartbeat moves the claim forward every 30 seconds, so a long reply never looks abandoned. The task alone ends the turn: it stops and awaits the heartbeat, saves the reply and releases the claim in one transaction, then signals the listener. A client that sees `[DONE]` can send again at once. A model error, the 600-second turn deadline, or a shutdown stores nothing and releases. A returning user learns the state from a `replying` field on the conversation, worked out from the claim against the database clock, and sees "Still answering…" until the full reply appears.

## What was decided, and why

The decisions are four dated addenda to [ADR 0002](../adr/0002-anthropic-sdk-not-agent-sdk.md) (an architecture decision record: a file recording one decision and why).

**2026-10-22, the claim.** Rejected: a Redis lock (a flag in Redis, hax's in-memory store: a second system for the row's state, taken before the ownership check), Postgres advisory locks (named locks the database hands out; each reply would hold a pooled database connection, one of a small reused set, throughout), and live replies shared across tabs. The two-minute window was the only thing that freed a conversation whose server died, so it had to outlast the longest normal reply.

**2026-10-27, the server owns the turn.** The heartbeat changed what the window means: it now bounds only how long a dead process blocks a conversation, not how long a reply can be. The deadline exists because of the heartbeat. The SDK (the model provider's client library) allows a 600-second timeout and two retries per call, so a stalled provider could otherwise keep a claim alive, and every send refused, for up to an hour. Rejected: running generation on Celery (hax's background-job runner; chat is streamed from the API, never queued), re-attaching a returning client to the live stream (it would need events shared across requests, where checking back needs one boolean), and a longer window. The client also picks each message's id, so a send that lost its connection can be checked, and a resend of the same id is refused instead of duplicated.

**2026-11-02, Stop.** Stop cancels only the part of the task that reads the model's stream, so the save still runs and the text written so far is kept. A blank partial stores nothing, because the model API (the provider's service the harness calls) rejects a whitespace-only text block and storing one would break every later turn.

**2026-11-02, Try again.** A retry claims the turn first and only then reads the last two messages, so another page's answer is visible before the rule decides. It also states the rule that matters most: a reply is stored only by the turn that still holds the claim.

## The episode

The first bug was the one in the idea: two sends mid-reply loaded a history ending in an unanswered question and saved replies in completion order, pairing answers with the wrong questions. `9bb551c` added the claim. A week later, `7b15a02` moved the reply into a server task, so a user who closes the tab or drops offline comes back to the whole reply.

Under the "only the claim holder stores" rule, a turn whose claim had lapsed and been taken by another turn correctly stored nothing, but its stream still ended with `[DONE]`, telling the browser a discarded reply had been saved. `2dd6817` made the save report whether it released its own claim; when it did not, the listener gets `reply_failed` and a warning names the conversation. The test in [`tests/api/test_reply_takeover.py`](../../tests/api/test_reply_takeover.py) stages the takeover for real, aging the claim past the window mid-reply and sending a second turn instead of mocking the release.

## Look at

- [`docs/adr/0002-anthropic-sdk-not-agent-sdk.md`](../adr/0002-anthropic-sdk-not-agent-sdk.md) — the four addenda.
- [`apps/api/turns.py`](../../apps/api/turns.py) — the turn task, heartbeat, deadline, Stop and drain.
- [`packages/db/repos/conversations.py`](../../packages/db/repos/conversations.py) — `claim_turn`, `refresh_turn`, `release_turn`, `TURN_WINDOW`.
- [`apps/api/chat_service.py`](../../apps/api/chat_service.py) — `persist_assistant_turn`: save and release in one transaction.
- [`tests/api/test_turn_guard.py`](../../tests/api/test_turn_guard.py), [`tests/api/test_server_turn.py`](../../tests/api/test_server_turn.py), [`tests/api/test_reply_takeover.py`](../../tests/api/test_reply_takeover.py) — the claim, the server turn, the lost claim.
- `9bb551c` — one reply at a time per conversation.
- `7b15a02` — a reply finishes even when the client leaves.
- `ddbb602` — Stop keeps what was written.
- `e57d151` — Try again; only the claim holder stores its reply.
- `2dd6817` — a reply whose claim was lost ends failed, not `[DONE]`.
