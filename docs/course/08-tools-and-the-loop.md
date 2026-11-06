# 08. Tools and the loop

Threads: A (agentic LLM systems) · B (full-stack engineering)

## The idea

The first version of hax searched the user's documents on every message and pasted the results into the prompt (the text sent to the model). That works, but it searches when nothing needs searching, and it searches only once, with the user's exact words.

The alternative is to give the model tools. A tool is a function the model can ask the program to run, like "search the documents for X." The model reads the question, decides whether it needs a tool, asks for one, reads the result, and either asks again or answers. That cycle is the agent loop. It is like a researcher with a library card: they choose when to go to the stacks, and they can go back with a better query.

## How hax does it

The loop is hand-written in [`packages/core/agent/harness.py`](../../packages/core/agent/harness.py), the harness (the code around the model that runs the loop). It is built on the Anthropic SDK (software development kit: the plain library for calling Claude). Each pass streams a model call (the reply arrives in pieces as it is written) with the tool list attached. If the model stops because it wants a tool, the harness runs every tool it asked for, appends the results to the conversation, and calls the model again. If it stops for any other reason, the answer has already streamed and the turn ends.

The tools live in [`packages/core/agent/tools.py`](../../packages/core/agent/tools.py): `search_documents`, `calculator`, `get_current_datetime`, and a mocked `send_email` with a fixed recipient. A bad tool name, invalid input or a crash inside a tool becomes an error result the model can see, not a crash of the turn. The user's identity reaches tools through a `ToolContext` the server builds, never through anything the model writes, so a search always runs over the asking user's own chunks.

Two limits keep the loop honest. `MAX_ITERS` caps a turn at five tool rounds. If the model is still asking for tools after the fifth, the harness makes one last call with no tools at all, using `FINAL_ANSWER_PROMPT`: answer now with what you have, and say plainly what you could not verify.

The harness yields three kinds of events: content (text to show), status (a short note such as "Searching documents…") and sources. `search_documents` returns a `ToolOutput` holding both the text the model reads and the list of passages behind it. The harness sends only the text to the model and passes the sources on; the server saves them with the message, and the client shows them under the answer.

## What was decided, and why

`e70f420` made `/api/chat` the single chat route (the server address the app sends chat messages to), running this loop, and retired both the always-search route and an earlier side-by-side route built on Anthropic's Agent SDK (a higher-level library that runs the agent loop for you). The [ADR 0002](../adr/0002-anthropic-sdk-not-agent-sdk.md) addendum of 2026-07-21 explains the choice of the plain SDK: the loop needs exactly the low-level control (tools, streaming events, per-call model choice) that the Agent SDK hides. It also records the costs accepted: a turn can now be up to six model calls, and the chat now mixes untrusted document text with tools the model can trigger on its own.

The sources decision, in the 2026-10-06 addendum, rejected the native citations of Anthropic's API (the service a program calls to reach the model), where the model marks which sentence rests on which passage. Those depend on one provider's request format; the harness approach works with any model that calls tools. The trade is granularity: the footer says what was searched and found, not which sentence came from where. Sources are never replayed into later prompts.

Members can pick a model. `11b3c9a` turned that field into an allowlist of the three ids the dropdown offers (`claude-haiku-4-5`, `claude-sonnet-4-6`, `claude-opus-4-8`, in [`packages/core/schemas/chat.py`](../../packages/core/schemas/chat.py)). Before, a member could name any model id the SDK accepted, so a member could pick any model, including the most expensive; now anything else is a 422 (a "bad input" error) before a turn is spent. The web's option list is typed against the generated API types (TypeScript definitions produced from the server's own description of its endpoints), so the two cannot drift silently. Demo visitors stay on the default model.

## The episode

The single-route change went through an adversarial review (a structured hunt for bugs by reviewer agents), and `c41cf5c` closed all six findings. The most serious was a silent turn: if every pass stopped to call a tool until `MAX_ITERS` ran out, the model never wrote an answer. Status notes are not saved, so the user would get nothing. The no-tools fallback call fixed it, verified live by forcing the limit to one. The same commit told the model to search first when a question could be answered from the documents, and to always say whether it had checked them.

Eight days later came a measured problem. With Haiku, the default model, `438b574` records that it skipped `search_documents` on 8 of 8 questions about unfamiliar topics, and claimed to have checked documents it had never searched. A new instruction was added to the system prompt (the standing instructions sent with every turn): search before saying you cannot help, and never claim something is absent from the documents without having searched. With it, Haiku searched on 6 of 8. The commit calls that "better, not guaranteed." A prompt asks a model to behave; it does not make it.

## Look at

- [`packages/core/agent/harness.py`](../../packages/core/agent/harness.py) — the loop, `MAX_ITERS`, `FINAL_ANSWER_PROMPT`, the three event kinds
- [`packages/core/agent/tools.py`](../../packages/core/agent/tools.py) — the four tools, `ToolContext`, `ToolOutput`
- [`packages/core/schemas/chat.py`](../../packages/core/schemas/chat.py) — the model allowlist
- [`apps/api/routers/chat.py`](../../apps/api/routers/chat.py) — `AGENTIC_SYSTEM`, the system prompt
- [ADR 0002](../adr/0002-anthropic-sdk-not-agent-sdk.md) — addenda of 2026-07-21 (single agentic route) and 2026-10-06 (sources observed by the harness)
- [ADR 0011](../adr/0011-auth-architecture.md) — the 2026-10-11 model allowlist note
- `e70f420` — collapse to a single agentic `/api/chat` route
- `c41cf5c` — the review's findings closed: no-tools fallback, search-first steering
- `438b574` — never claim document absence without searching (8/8 skipped, then 6/8 searched)
- `b1646f9` — answers carry the passages they were searched from
- `11b3c9a` — the request's model is an allowlist of the offered ids
