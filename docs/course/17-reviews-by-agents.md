# 17. Reviews by agents

Threads: A (agentic LLM systems) · C (building with Claude Code)

## The idea

A code review is a second reader looking for mistakes before a change lands. In hax most code is written by AI agents, so most review is done by agents too. Two kinds are used, like a building that gets both a general inspector and, for the risky parts, a panel of specialists who each check one system.

- The **fresh-eyes reviewer** is one new agent, with no memory of how the change was made, that reads the whole change and reports real defects.
- The **adversarial review** is a crowd of agents. Each one hunts through one "lens" (security, races, migrations, and so on), and every finding is then attacked by other agents trying to prove it wrong. Only findings that survive are reported.

## How hax does it

The adversarial review is a committed workflow script, [`.claude/workflows/adversarial-review.js`](../../.claude/workflows/adversarial-review.js), committed in `1a45967` on 2026-09-08. It has four phases, listed at the top of the file:

1. **Find.** One agent per lens, in parallel. There are ten built-in lenses, each a one-line brief: authorization, injection, auth and crypto, concurrency, data and migrations, operations and deploy, production scale, test integrity, error handling and leaks, and public-repo hygiene with doc accuracy. Each must report findings with file and line evidence and a concrete scenario; "an empty list is a valid result".
2. **Dedup.** One agent merges findings that share a root defect.
3. **Verify.** Each finding faces skeptics who read only the files it cites. Critical, high and medium findings get three votes: *repro* (walk the scenario against the real code), *impact* (is it already covered by another layer?) and *skeptic* (find the strongest reason it is wrong). Low findings get the skeptic only. A finding survives when fewer than half its votes refute it.
4. **Synthesize.** One agent writes the ranked report, including the refuted findings, one line each, "so a wrong refutation can be spotted".

The script also guards its cost. A header comment estimates about 60 agents per run, and the script refuses to start unless the launcher states the subscription tier (`329fd98`). The more expensive model is kept to the three most sensitive lenses and the two single-agent stages. The `whenToUse` line sets a ceiling in tokens (the small chunks of text a model reads and writes, the unit its use is measured in): 3M for a slice (one small, complete piece of work), 7M for the whole project.

The fresh-eyes reviewer has no file of its own. It is a step inside other processes: in the feature chain (the scripted sequence of agents that builds one approved feature, [`.claude/workflows/feature-chain.js`](../../.claude/workflows/feature-chain.js)) its prompt is "Walk the change caller-first. Real defects only.", and the morning digest (the daily report that opens each work day; see [chapter 19](./19-the-factory.md)) runs one over each night's pull requests before any merge.

## What was decided, and why

Not every change needs the expensive review. The [blind-tests skill](../../.claude/skills/blind-tests/SKILL.md) sorts every change into one of three **review tiers** before any code is written (`1944bf2`):

| Tier | When | Review |
|---|---|---|
| 1 | auth, security, isolation, concurrency, a pool, deploy or infra, a schema, data deletion, a dependency, more than one store | blind tests, fresh-eyes, adversarial review |
| 2 | any other behavior change | blind tests, fresh-eyes |
| 3 | refactor, comments, docs, test-only | fresh-eyes |

The adversarial review is "never automatic": it runs only after a cost preview and the maintainer's "go", once per item, not per bite. A main-lane item is one task the maintainer works on with the main Claude session, cut into small steps called bites, each built, reviewed and committed in turn. A tier-1 change may skip it only when the fresh-eyes review already covered that surface's specific risk, and the hand-off must say so in one line.

The latest refinement treats comments as code (`e8e4f7f`, 2026-11-06). A comment that claims something about other code ("never", "always", who calls this) must come with the file and line that make it true, or it is a finding. The reviewer also re-reads every comment inside a changed function and searches for comments elsewhere that name a changed symbol, "since no test runs prose". This matters here because [`CLAUDE.md`](../../CLAUDE.md) writes comments for two readers, future developers and the AI assistant, and a wrong comment misleads the next agent as surely as a wrong test.

The trade-off is cost. The script's header puts one run at roughly a quarter of a five-hour usage window on the plan it names, so the crowd is kept for tier 1, and every other change gets one careful reader.

## The episode

A whole-project adversarial review ran in July 2026, before the workflow file was committed to the repo. Its fixes landed as separate commits.

- `e433346` (2026-07-09): when a user closed the tab mid-reply, the server's cancellation reached the code that saves the partial answer. The first database call inside the save was canceled, so the partial reply was silently lost. The fix shields the save until it completes. The same commit fixed a second gap: if the task queue was down right after an upload was saved, the document stayed `pending` forever with no job queued. It is now marked `failed`.
- `fbb0898` (2026-07-10): retrieved document text was wrapped in `<context>` tags in the prompt. A document containing a literal `</context>` could close that fence early and place its own text where instructions go, a form of prompt injection (text that tries to steer the model). The tags are now stripped from document content and filenames.

The first message says its two findings were "both verified"; the second calls its fix a "cheap guard from the whole-project AR pass". Verifying is the point of the vote stage: a crowd of finders produces noise, and the skeptics filter it.

## Look at

- [`.claude/workflows/adversarial-review.js`](../../.claude/workflows/adversarial-review.js): lenses, votes, cost guard.
- [`.claude/skills/blind-tests/SKILL.md`](../../.claude/skills/blind-tests/SKILL.md): review tiers, the fresh-eyes rules, comments reviewed like code.
- [`.claude/workflows/feature-chain.js`](../../.claude/workflows/feature-chain.js): the fresh-eyes stage in the feature lane.
- `e433346`: partial-turn save shielded from cancellation; broker outage no longer strands uploads.
- `fbb0898`: `<context>` fence tokens removed from retrieved text.
- `1a45967`: the workflow committed with cost-tiered models.
- `329fd98`: refuses to run without a plan acknowledgement.
- `1944bf2`: review tiers for the main lane.
- `e8e4f7f`: reviewers check what comments claim.
