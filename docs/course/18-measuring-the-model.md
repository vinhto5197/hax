# 18. Measuring the model

Threads: A (agentic LLM systems) · C (building with Claude Code)

## The idea

Ordinary tests check code that always gives the same answer. A language model does not: ask it the same question twice and the wording, and sometimes the substance, can change. So a change to the prompt, a tool or the model cannot be judged by trying a few questions and getting a good feeling. An **eval** (evaluation) is a fixed set of questions with written expectations, run through the real system and scored, so a change is judged by numbers.

A cooking analogy: rather than tasting the soup once and saying "seems fine", you keep a scorecard of twenty dishes, cook all of them after every recipe change, and note exactly which ones got worse.

## How hax does it

`make eval` lives in [`evals/`](../../evals/README.md). The pieces:

- **Cases** ([`evals/cases.jsonl`](../../evals/cases.jsonl), loaded by [`evals/cases.py`](../../evals/cases.py)): one JSON object (a standard text format for structured data) per line with a question, its context (which documents, an optional About-you note, which is a member's short note about themselves, earlier turns) and what a good answer shows. Each case is a **must** (counts toward pass or fail) or a **probe** (reported, never fails a run). The file is checked before any paid call, so a typo costs nothing.
- **Corpus** ([`evals/corpus/`](../../evals/corpus/)): two invented documents, a grammar of a made-up language called Nevron and the notes of a fictional cave survey, "so the model cannot answer from what it already knows".
- **The runner** ([`evals/run.py`](../../evals/run.py)) drives the same agent loop, system prompt and retrieval as the chat route, on its own database, Redis slot (a separate numbered store inside Redis, the in-memory data store) and storage bucket (a container for uploaded files).
- **Two graders.** [`evals/checks.py`](../../evals/checks.py) does what code can settle: which tools fired, required or forbidden phrases, an exact reply, a Markdown table. [`evals/judge.py`](../../evals/judge.py) asks a second model (an "LLM as judge") whether the answer makes each key point and whether every claim is **grounded**, meaning supported by what the model was actually given. That is the passages its searches returned, not the source documents: "a claim true in a document the search did not return is still unsupported".
- **The report** ([`evals/report.py`](../../evals/report.py)) prints a summary and **flips** against a baseline: `broke` (passed before, fails now) and `fixed`. An `error` (the API could not finish) is never a flip; it makes the run untrustworthy instead.

The README lists when a change must run it: the member system prompt, the agent loop or its tools, retrieval, or the default model. A `broke` flip on a must case is rerun once, "because the same model fails a case on one run and passes it on the next". CI (continuous integration: the checks GitHub runs on every push) never runs it, because it spends money.

## What was decided, and why

Three decisions are recorded in ADR 0002's addenda ([`../adr/0002-anthropic-sdk-not-agent-sdk.md`](../adr/0002-anthropic-sdk-not-agent-sdk.md)).

**Observe the loop through two callbacks** (2026-11-04). The agent loop takes optional `on_usage` and `on_tool_result` hooks (callbacks: functions the loop calls at set moments). The chat route passes neither, so nothing changes for users. The eval uses them to grade against exactly what the model saw and to report cost. Rejected: a usage event in the stream (every consumer would have to drop it) and reading counts from logs (fragile, and logs never carry tool output, by design). The runner is "our own thin code", not an eval platform: at tens of cases and one developer, dashboards and labeling queues do not apply.

The same addendum records what measurement showed. A full run cost about $0.43 on `claude-haiku-4-5` (35 cases). Right answers' passages sat at cosine distance (a measure of how far apart two meanings are; lower is closer) 0.38 to 0.62, while for off-corpus questions (ones the documents cannot answer) the nearest chunks sat at 0.52 to 0.80. The ranges overlap, so any distance cutoff strict enough to drop the off-corpus chunks would drop right answers too. The cutoff stays unset, and honesty is left to the model.

**The judge answers by tool call** (2026-11-05). The judge first wrote its verdict as JSON text. On `claude-sonnet-4-6` that text dropped or doubled a closing brace in about one case in twenty, and each such case became an error. Now the judge must call a tool, `record_verdict`, and the API returns its input already parsed. Rejected: repairing the text ("grades on a guess") and provider-specific structured-output parameters, which the ADR keeps out to stay portable across providers.

**A committed baseline** (`42eb45a`, 2026-11-06). `make eval-baseline` writes [`evals/baseline.json`](../../evals/baseline.json): each case's outcome and per-check summary, no answers. Committing it means "a baseline move is a diff a reviewer sees". The current baseline records the model, the judge, the commit it ran on, and one failing case, a probe.

## The episode

On 2026-11-06, `6c58180` fixed a quiet lie. When the embedding service (the outside service that turns text into numbers for search) or the database failed, retrieval raised nothing and returned an empty list. To the model an empty search means "your documents don't say", so it told members, falsely, that their documents lacked the answer. The eval had the same blind spot: it "graded a broken stack as a model that finds nothing". Retrieval now raises `RetrievalUnavailable`, the search tool returns an error result, and the eval counts it as a stack fault. ADR 0007 got an addendum ([`../adr/0007-voyage-ai-for-embeddings.md`](../adr/0007-voyage-ai-for-embeddings.md)).

Later that day, `2dfcc52` took the lesson one step further. The system prompt now says a tool error that retrying does not fix is reported as that step failing, "never as the information being absent". It added two cases: a must case that a number stated for one thing is not borrowed for another, and a probe recording that a re-asked answer can still name a deleted document. The baseline moved in the same commit.

## Look at

- [`evals/README.md`](../../evals/README.md): running, when it is required, reading results, adding a case.
- [`evals/run.py`](../../evals/run.py), [`evals/checks.py`](../../evals/checks.py), [`evals/judge.py`](../../evals/judge.py), [`evals/report.py`](../../evals/report.py).
- [`evals/baseline.json`](../../evals/baseline.json): the committed baseline.
- [ADR 0002](../adr/0002-anthropic-sdk-not-agent-sdk.md), addenda 2026-11-04 and 2026-11-05.
- [ADR 0007](../adr/0007-voyage-ai-for-embeddings.md), addendum 2026-11-05.
- `42eb45a`: the baseline becomes a committed snapshot.
- `d554c9e`: the judge reads only its forced tool call.
- `6c58180`: a search outage is an error, not an empty search.
- `2dfcc52`: tool errors reported as failures; two new cases.
