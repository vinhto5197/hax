# 05. Conversation memory

Threads: A (agentic LLM systems) · B (full-stack engineering)

## The idea

A language model remembers nothing between calls. Each request is read fresh, as if for the first time. If you ask "what is the capital of France?" and then "and its population?", the second request means nothing unless it also carries the first question and its answer.

So a chat app has to supply the memory. Before every reply, it gathers the conversation so far and sends all of it, oldest first, with the new question at the end. Picture a consultant with no memory of past meetings who reads the whole file before each one.

That has a cost. The file grows, and the model reads every word of it on every turn, and is billed by the token (a word or piece of a word, the unit models read and charge by). Prompt caching (the provider keeps the already-processed start of a request for a few minutes, so a later request that begins with exactly the same content reads that part at a fraction of the price) is how hax keeps the growing file affordable.

## How hax does it

Memory is replayed from Postgres, the database where every message is already stored. `load_history` in [`apps/api/chat_service.py`](../../apps/api/chat_service.py) runs before each reply. It calls the function of the same name in the repository layer (the code that reads and writes the database), [`packages/db/repos/conversations.py`](../../packages/db/repos/conversations.py), which selects each message's role and text, oldest first, joined to the conversation's owner so another user's id returns nothing. The result is the `messages` list the model API expects. The user's new message is already saved, so it lands last.

A few rules shape that list:

- **Text only.** The sources shown under an answer are stored on the message but never sent back to the model. [ADR 0002](../adr/0002-anthropic-sdk-not-agent-sdk.md)'s 2026-10-06 addendum states this contract.
- **No tool turns.** Inside one reply the harness (the loop that calls the model and runs the tools it asks for) may call tools several times. It works on a local copy of the list, so those intermediate steps are never saved or replayed. Only the text the user saw streamed is saved; tool requests and results are not.
- **Same-role turns merged.** A failed reply stores no assistant message, so a resend can follow its own question. Those are joined with a blank line so the list always alternates between user and assistant.
- **Full history, no windowing.** Every turn sends the whole conversation. The function's docstring (the description written at its top) says so plainly: no windowing in v0.

Caching lives in [`packages/core/agent/harness.py`](../../packages/core/agent/harness.py). Before each model call, `_cache_last` marks the last block of the last message with `cache_control: ephemeral` (the provider's five-minute cache). One marker caches everything before it: the tool definitions, the system prompt and the conversation. It returns a copy, so the caller's list is never changed. After each call, `_report_usage` logs four numbers: fresh input tokens, output tokens, tokens read from cache and tokens written to it.

## What was decided, and why

**Postgres is the single source of truth for memory.** When the Agent SDK route (a second chat route, since retired, that ran Claude through Anthropic's Agent SDK) got the same feature (`25a6817`), its library offered its own session files on disk. The commit rejected them: a second copy of the history could drift from the database, and on a new machine or after temp files were cleaned, the chat would forget again while Postgres still had everything. Instead the route flattened past turns into one tagged transcript inside the prompt, keeping the route stateless.

**Empty messages are refused at the door.** `bc7b2d9` made the request schema (the declared shape a request must have) in [`packages/core/schemas/chat.py`](../../packages/core/schemas/chat.py) reject empty or whitespace-only prompts with a 422 (an HTTP status meaning the request was understood but invalid). The reason is specific to replay: the model API rejects empty content, and a saved empty turn would be replayed into every later request, breaking the conversation for good.

**Where the cache marker goes is a choice.** A marker on content that will not recur exactly pays to write and never gets read back. That rule moved the marker once, as the episode tells.

There is no separate ADR for caching; the reasoning lives in the harness and its commits.

## The episode

From `268d418` on 2026-06-02, hax saved every message but still sent the model only the newest one. A comment in `chat_service.py` said so: the model was "amnesiac for now", with history replay "a deliberate follow-up". That follow-up was `bc7b2d9`, on 2026-06-11, named "de-amnesia": the route loaded the saved turns and sent them as the messages list. `25a6817` did the same for the Agent SDK route the next day.

Caching came a month later, in `25809c7`. Retrieval then worked by pasting found document passages into the newest user message. Those passages were never saved, since replay sends the raw question. So the newest message never appeared byte-for-byte again, and caching it would pay the write premium for nothing. The commit placed the marker one message earlier, on the last completed turn. It also noted that short chats would show zero cache activity, because the model in use only caches prefixes (the opening stretch of a request) of 4,096 tokens or more: expected, not a bug.

Two weeks later, retrieval became a tool the model calls (`779260f`), and the passages stopped being pasted into the question. Now one reply can make several model calls, each repeating everything before it plus a new tool result. The marker moved to the last message, so each call in the loop re-reads the growing prefix. The commit records the live check: one call wrote 6,266 tokens to the cache and the next call read the same 6,266 back, within a turn and across turns.

## Look at

- [`apps/api/chat_service.py`](../../apps/api/chat_service.py): `load_history`, merging same-role turns, full history every turn.
- [`packages/db/repos/conversations.py`](../../packages/db/repos/conversations.py): the owner-scoped history query.
- [`packages/core/agent/harness.py`](../../packages/core/agent/harness.py): `_cache_last`, `_report_usage`, the local copy of `messages`.
- [`packages/core/schemas/chat.py`](../../packages/core/schemas/chat.py): empty prompts rejected.
- [`docs/adr/0002-anthropic-sdk-not-agent-sdk.md`](../adr/0002-anthropic-sdk-not-agent-sdk.md): sources are never replayed into the prompt.
- `268d418`: messages saved to Postgres; the model still saw only the newest.
- `bc7b2d9`: replay persisted history into the prompt ("de-amnesia").
- `25a6817`: the same for the Agent SDK route, by transcript flattening.
- `25809c7`: prompt caching with the marker on the last completed turn.
- `779260f`: the harness, with one moving marker on the last message.
