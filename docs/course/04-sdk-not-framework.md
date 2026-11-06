# 04. An SDK, not a framework

Threads: A (agentic LLM systems) · C (building with Claude Code)

## The idea

To talk to Claude from code, you need a client library. There is a choice of how much that library does for you.

An SDK (software development kit: a library that wraps a service's web API, the set of requests a server accepts over the internet, in ordinary function calls) does little. You build the request, it sends it, you get the reply. A framework does much more: it decides how prompts are assembled, how tools are called, how memory is kept. That saves work when its choices match yours, and costs control when they don't.

Think of good kitchen knives versus a meal kit: the kit is faster the first night, but changing the recipe means working around someone else's packaging. hax picked the knives. It calls Claude through the plain `anthropic` Python SDK and writes the rest itself.

## How hax does it

Today the chat's whole model-facing layer is [`packages/core/agent/harness.py`](../../packages/core/agent/harness.py), about 250 lines, with the tools in [`packages/core/agent/tools.py`](../../packages/core/agent/tools.py). A harness here means the loop around the model: it sends the conversation, streams back text, and when the model asks for a tool, runs that tool and sends the result back. A system that lets the model choose its own next step this way is called agentic. The model never runs anything itself; it only writes a request that the harness acts on.

The harness calls `messages.stream(...)` on the SDK's client and forwards each text piece. If the model stopped to use a tool, the harness runs it from a registry (a lookup table of the tools by name), appends the result, and calls the model again. It does this at most `MAX_ITERS` times (five). If the model is still asking for tools after that, the harness makes one last call with no tools offered, so the turn always ends in an answer.

It started much smaller. The first client, `805f020` on 2026-05-16, was 21 lines in `packages/core/llm/client.py`: one function that opened a stream and yielded text. By `6511aac` it was 22.

## What was decided, and why

Two ADRs from 2026-05-21 record the choice.

[ADR 0002](../adr/0002-anthropic-sdk-not-agent-sdk.md) compares the plain SDK with the Claude Agent SDK (a library that runs the bundled Claude Code command-line program as a subprocess, a separate program the server starts and talks to). The Agent SDK could bill against a developer subscription instead of API credits (prepaid usage of the model, charged per call), which looked attractive. After hands-on testing it was rejected because:

- every request goes through a subprocess, adding latency (delay before a reply starts) and memory, and production would need Node.js (the runtime that runs JavaScript outside a browser) next to Python;
- it loads project and user settings files on its own (more in the episode);
- its stream arrived server-buffered, landing all at once;
- its options did not expose `model`, `max_tokens` (the cap on reply length) or thinking settings (how much the model reasons before answering).

The plain SDK gives direct calls, explicit control and token-by-token streaming (a token is a word or piece of a word, the unit models read, write and bill by), at the cost of paying per call in API credits.

[ADR 0004](../adr/0004-skip-langchain-in-v0-llm-client.md) rejects a second layer: LangChain (a popular Python framework that wraps many model providers behind one interface). The first draft of the client used a LangChain wrapper and ran to 58 lines of message conversion and adapter code. The direct SDK did the same job in 22. ADR 0004 expected LangChain to return for retrieval. It did, but only a little: [ADR 0009](../adr/0009-voyage-sdk-direct-langchain-splitter-only.md) later limited it to splitting text into chunks.

The 2026-07-21 addendum to ADR 0002 says the choice was strengthened, not weakened, when hax became agentic. Tool use needs exactly the low-level control the Agent SDK hides: passing `tools=...`, reading streaming events, choosing the model per call. It also names two accepted costs: one chat turn can now be up to `MAX_ITERS` + 1 model calls instead of one, and the chat now mixes untrusted document text with tools the model can call on its own.

## The episode

The plain SDK was chosen on 2026-05-21, but the Agent SDK was kept alive as a sibling route, `POST /api/chat-agent-sdk`, so the two could be compared side by side (`86f1d1e`). A UI dropdown picked the backend.

Wiring it up exposed three surprises, which `86f1d1e` fixed in `packages/core/llm/agent_client.py` and `412b850` wrote into ADR 0002:

1. **Auth precedence.** The bundled program preferred an API key over the subscription token whenever both were visible, and the options merged with the server's environment rather than replacing it. The fix blanked the API key in the subprocess's environment.
2. **Context bleed.** Even with an empty system prompt (the standing instructions sent ahead of the conversation), the program read `CLAUDE.md`, the instruction file for Claude Code in the repo (the project's code repository), into every request. Requests were about 22,000 input tokens. The chat answered as if the user were a developer working on hax. With all three fixes in place, the same request was about 50 tokens.
3. **Tool hygiene.** No tools and one turn, to keep it a plain chat.

`412b850` also recorded a layer-by-layer test. Turning off settings loading alone was not enough: with the working directory at the repo root, the model decided the question was about the codebase and asked for a file-reading tool. The program could not run it and could not take another turn, so it failed with "Reached maximum number of turns (1)". The test also traced a change in the chat's tone to the working directory: when the project's `CLAUDE.md` was loaded, the answers took on its confident voice. The ADR's lesson: behavior that depends on files near wherever the server runs is unacceptable for a product backend.

On 2026-07-21, `e70f420` retired the sibling route and `packages/core/llm/`, and `/api/chat` became the single route, running the hand-rolled harness from `779260f`.

## Look at

- [`docs/adr/0002-anthropic-sdk-not-agent-sdk.md`](../adr/0002-anthropic-sdk-not-agent-sdk.md): the comparison, the three subprocess fixes, the layer-by-layer table, the 2026-07-21 addendum.
- [`docs/adr/0004-skip-langchain-in-v0-llm-client.md`](../adr/0004-skip-langchain-in-v0-llm-client.md): 22 lines instead of a LangChain wrapper.
- [`docs/adr/0009-voyage-sdk-direct-langchain-splitter-only.md`](../adr/0009-voyage-sdk-direct-langchain-splitter-only.md): LangChain kept for text splitting only.
- [`packages/core/agent/harness.py`](../../packages/core/agent/harness.py): the tool-use loop, `MAX_ITERS`, the no-tools final call.
- [`packages/core/agent/tools.py`](../../packages/core/agent/tools.py): the tool registry.
- `805f020`: the first direct-SDK client, 21 lines (`packages/core/llm/client.py`).
- `6511aac`: the client at 22 lines.
- `86f1d1e`: Agent SDK sibling route with the three subprocess fixes.
- `412b850`: ADR 0002 records the route and the empirical findings.
- `779260f`: tool registry and hand-rolled harness.
- `e70f420`: one agentic `/api/chat`; the Agent SDK route retired.
