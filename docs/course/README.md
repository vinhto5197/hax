# How hax was built

This course walks through how hax, an AI chat product that answers questions from the user's own files, was built from an empty repo to a live service. Each chapter takes one idea, shows the code that carries it, gives the decision and the options it beat, and tells one thing that went wrong or surprised the people building it, with the commits to read. Every claim comes from a file, a decision record or a commit in this repo. Three threads run through the chapters. **A, agentic LLM systems**: how a program around a language model streams, remembers, searches, calls tools and is measured. **B, full-stack engineering**: the web app, the API, the database, background jobs, auth and deployment that any real product needs. **C, building with Claude Code**: how an AI coding assistant wrote most of the commits, and the instructions, reviews and tests that kept its work honest. Start with chapter 00. After that, read in order or follow one thread.

| # | Chapter | Threads |
|---|---|---|
| 00 | [What hax is, and how to read this](00-what-hax-is.md) | A · B · C |
| 01 | [Working with an AI pair: instructions, not prompts](01-an-ai-pair.md) | C |
| 02 | [One repo: services and shared libraries](02-one-repo.md) | B |
| 03 | [Streaming the reply](03-streaming.md) | A · B |
| 04 | [An SDK, not a framework](04-sdk-not-framework.md) | A · C |
| 05 | [Conversation memory](05-conversation-memory.md) | A · B |
| 06 | [Embeddings and search](06-embeddings-and-search.md) | A · B |
| 07 | [Work off the request](07-work-off-the-request.md) | B |
| 08 | [Tools and the loop](08-tools-and-the-loop.md) | A · B |
| 09 | [When the model invents](09-when-the-model-invents.md) | A · B |
| 10 | [Signing in](10-auth.md) | B |
| 11 | [Keeping users apart](11-keeping-users-apart.md) | B |
| 12 | [One reply at a time](12-one-reply-at-a-time.md) | A · B |
| 13 | [Deploying small](13-deploying-small.md) | B · C |
| 14 | [The demo and its limits](14-the-demo-and-limits.md) | A · B |
| 15 | [Looking like a product](15-looking-like-a-product.md) | B · C |
| 16 | [Tests you can trust](16-tests-you-can-trust.md) | B · C |
| 17 | [Reviews by agents](17-reviews-by-agents.md) | A · C |
| 18 | [Measuring the model](18-measuring-the-model.md) | A · C |
| 19 | [The factory](19-the-factory.md) | C |
| 20 | [Rules that hold](20-rules-that-hold.md) | B · C |
| 21 | [What v0 teaches](21-what-v0-teaches.md) | A · B · C |
