# The eval

`make eval` asks hax's real agent a fixed set of questions and grades every
answer, so a change to the prompt, the tools, retrieval or the model is
measured by which cases flip, not by impressions.

Each case goes through the same agent loop, system prompt, About-you framing,
tools and retrieval the chat route uses (`evals/run.py` drives
`stream_completion_agentic` directly; ADR 0002, 2026-11-04 addendum). Two
graders score the answer:

- **Code checks** (`evals/checks.py`): which tools fired, an exact reply,
  phrases the answer must or must not contain, a Markdown table. Free, and
  strict.
- **A judge model** (`evals/judge.py`, `claude-sonnet-4-6` by default): whether
  the answer makes each key point, and whether every claim is supported by
  what the model was actually given (the passages its searches returned, the
  tool outputs, the note, the earlier turns), never the source documents.

## Run it

```sh
make infra-up                      # Postgres, Redis, the S3 stand-in
make eval                          # the default model, claude-haiku-4-5
make eval MODEL=claude-sonnet-4-6  # another model under test
make eval RAG_MAX_DISTANCE=0.7     # a retrieval cutoff
```

`ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` come from your environment (direnv);
the runner never reads `.env`. It runs on its own stack: database `hax_eval`,
Redis db 13 and bucket `hax-eval`. `make eval` empties the database and Redis
db and ingests the corpus again on every run (the bucket keeps old objects
nobody references), so two runs at once would undo each other. It refuses to start
anywhere else. The retrieval, chunking and model settings your shell may
export are unset; a variant goes on the `make` command line, never in `.env`.

A few cases alone: `make eval EVAL_CASES=<file>` runs a JSONL file of cases
instead of the committed set. Running one case several times this way measures
a rate ("fails 3 runs in 6"), which one full run cannot show, for cents.

A run takes about a minute: four cases run at a time (`EVAL_CONCURRENCY` in
the environment changes it). Each run's report prints its cost, estimated from
list prices (`evals/prices.py`); a full run on Haiku is well under a dollar.

CI never runs it: it spends credits. CI runs its unit tests (`tests/evals/`).

## When a change must run it

A change to what the model sees or does runs `make eval` against the baseline
before it is presented or merged:

- the member system prompt, the About-you framing, or the request's model list
  (`apps/api/routers/chat.py`: `AGENTIC_SYSTEM`, `ABOUT_PREFACE`,
  `member_system`; `packages/core/schemas/chat.py`: `ModelId`);
- the agent loop or its tools, their descriptions and output text
  (`packages/core/agent/`);
- retrieval: chunking, embedding, top-k, the cutoff (`packages/core/rag/`);
- the default model (`DEFAULT_MODEL` in `packages/core/agent/harness.py`).

A plain `make eval` runs `claude-haiku-4-5` whatever the harness's default is,
so a change of model, or a model added to `ModelId`, runs
`make eval MODEL=<that model>` and compares it with the baseline
(`make eval-compare`).

A `broke` flip on a must case is rerun once, the whole eval, because the same
model fails a case on one run and passes it on the next. Broken on both runs,
the change stops there and the cases are named; `fixed` flips, probes and
errors go into the hand-off.

Two things that shape the prompt are not measured here: the guest prompt
(`packages/core/demo/prompt.md`, no cases) and history replay
(`load_history` in `apps/api/chat_service.py`, and what `apps/api/turns.py`
persists for it): a case's earlier turns are given as written, not replayed
from the database. The nightly routine cannot run the eval (no stack, no
keys), so items touching these paths are never queued for it. Runs take a
lock (`local/.eval.lock`): one at a time across the main checkout and feature
worktrees.

When a measured change lands, or the cases change, the run that checked it
becomes the baseline (`make eval-baseline`), so the next change is compared
with what is now on main. The baseline is `evals/baseline.json`, committed with
the change: each case's outcome and the per-check summary, no answers, so a
baseline move is a diff a reviewer sees. The full runs stay in `local/eval/runs/`. The feature lane's rule is in skill
`feature-chain`, the main lane's in skill `gate-block`.

## Read the results

Each run writes `local/eval/runs/<time>_<commit>.json` and an `.html` page
beside it (failures first, each case with its answer, checks, the judge's
reasons, retrieval rank and distances, and the passages the model saw).
Neither is committed. The terminal shows the summary:

- **must** cases count toward the result; **probes** are reported and never
  fail a run.
- **flips** against the baseline: `broke` (passed then, fails now) and
  `fixed`.
- **errors** are cases the model or judge API could not finish. They are
  never counted as failures or flips, and they make the run untrustworthy.
- **recall@k**: of the cases that name an expected passage, how many found it
  in the top results for the question.
- **distances**: each case records the cosine distance of its expected
  passage and of the nearest chunk. Right answers' passages and off-corpus
  questions' nearest chunks overlap in distance (ADR 0002, 2026-11-04
  addendum), so `RAG_MAX_DISTANCE` stays unset and honesty is left to the
  model.

The runner (`python -m evals.run`) exits 0 when every must case passed, 1
when a must case failed or any case errored, and 2 when the run could not
start (a bad case file, the wrong stack, a setup failure or a failed
preflight); `make eval` itself reports any non-zero exit as make's own 2.

```sh
make eval-baseline RUN=<file>.json   # writes evals/baseline.json; flips are reported against it
make eval-compare A=<file>.json B=<file>.json
```

`eval-compare` matches cases by id; a case whose line was edited between the
two runs is reported as `changed`, never as a flip.

## Add a case

One JSON object per line in `evals/cases.jsonl`:

```json
{"id": "grammar-fact", "tier": "must", "tags": ["retrieval"],
 "question": "According to my documents, which suffix marks the accusative (direct object) case in Nevron?",
 "context": {"documents": ["nevron_grammar.md"]},
 "expect": {"tools": ["search_documents"], "key_points": ["the accusative suffix is -en"],
            "grounded": true, "contains_any": ["-en"],
            "passage": {"document": "nevron_grammar.md", "contains": "accusative"}}}
```

- `context`: `documents` names the corpus files the answer should come from;
  the whole corpus stays searchable, so the others are distractors. An empty
  list runs the case as a member with no documents. `note` is an About-you
  note; `history` is earlier turns, `[{"role": "user", "content": "..."}]`.
- `expect`: every field is optional and a case runs only the checks it names.
  `tools` is the exact set of tool names (`[]` means none may fire);
  `exact_reply`, `contains_any`, `contains_none` ignore case, commas and
  spacing; `table` wants a Markdown table; `key_points` and `grounded` go to
  the judge; `passage` drives the retrieval score.
- A retrieval case names `"tools": ["search_documents"]`: the judge counts the
  key points as support, so without the tools check an answer from memory
  would pass (`tests/evals/test_committed_cases.py` enforces it).
- The file is checked before any API call; an error names the line.
- A case for a bug found by hand is shaped like the reported session (its
  note, a question needing as many searches, earlier turns in
  `context.history`) and fails before the fix; a simpler case can pass while
  the real session still fails. Its checks look for the bug's shape wherever
  it appears (a forbidden opener anywhere, not only a required phrase
  somewhere).
- Everything here is public: no personal data, no real user content.

The corpus (`evals/corpus/`) is two invented documents, a grammar of the
constructed language Nevron and the field notes of a fictional cave survey, so
the model cannot answer from what it already knows.

Key points for the general-knowledge cases follow these sources:

- `sky-blue`: NASA Space Place, "Why Is the Sky Blue?"
- `seasons`: NASA Space Place, "What Causes the Seasons?"
- `tides`: NOAA Ocean Service, "What causes tides?"
- `note-irrelevant`: water boils at 100 °C at sea level (standard pressure).
