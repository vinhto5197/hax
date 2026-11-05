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

A run takes two to four minutes. Measured on 2026-11-05 with 23 cases (an
estimate from list prices, `evals/prices.py`):

| Model under test | Model | Judge | Total |
|---|---|---|---|
| claude-haiku-4-5 | ~$0.13 | ~$0.17 | ~$0.30 |
| claude-sonnet-4-6 | ~$0.36 | ~$0.18 | ~$0.54 |

CI never runs it: it spends credits. CI runs its unit tests (`tests/evals/`).

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

The runner (`python -m evals.run`) exits 0 when every must case passed, 1
when a must case failed or any case errored, and 2 when the run could not
start (a bad case file, the wrong stack, a setup failure or a failed
preflight); `make eval` itself reports any non-zero exit as make's own 2.

```sh
make eval-baseline RUN=<file>.json   # flips are reported against this run
make eval-compare A=<file>.json B=<file>.json
```

`eval-compare` matches cases by id; a case whose line was edited between the
two runs is reported as `changed`, never as a flip.

Model answers vary between runs. On 2026-11-05 four Haiku runs failed between
none and two cases each, with one case (radio-channel) failing in two of them,
so a single flip is a lead to read, not a verdict.

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
- Everything here is public: no personal data, no real user content.

The corpus (`evals/corpus/`) is two invented documents, a grammar of the
constructed language Nevron and the field notes of a fictional cave survey, so
the model cannot answer from what it already knows.

Key points for the general-knowledge cases follow these sources:

- `sky-blue`: NASA Space Place, "Why Is the Sky Blue?"
- `seasons`: NASA Space Place, "What Causes the Seasons?"
- `tides`: NOAA Ocean Service, "What causes tides?"
- `note-irrelevant`: water boils at 100 °C at sea level (standard pressure).
