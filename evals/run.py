"""The eval runner: `make eval` (python -m evals.run).

Drives hax's real agent loop, the chat route's own system prompt and note
framing (`member_system`), its tools and its retrieval over a committed corpus,
then grades each answer with code checks and the judge. Runs as two seeded
eval members on the isolated eval stack the Makefile points it at (database
hax_eval, Redis db 13, bucket hax-eval); it never chooses a connection itself.
API keys come from the environment only. Spends credits: never run in CI.

Exit codes: 0 every must case passed; 1 a must case failed or any case errored
(the run is not trustworthy); 2 the run could not start (bad case file,
preflight).
"""

import argparse
import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text

from apps.api.routers.chat import member_system
from evals import report
from evals.cases import Case, CaseFileError, load_cases
from evals.checks import code_checks
from evals.judge import AnthropicJudge, Judge, Seen
from evals.prices import usd
from packages.core import storage
from packages.core.agent.harness import ToolResult, Usage, stream_completion_agentic
from packages.core.agent.tools import ToolContext
from packages.core.auth.passwords import hash_password
from packages.core.rag import retrieval
from packages.core.rag.ingest import ingest_document_async
from packages.core.rag.retrieval import retrieve
from packages.db import AsyncSessionLocal, engine
from packages.db.models import Document
from packages.db.repos import documents, users
from packages.db.user_context import current_user_id

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases.jsonl"
CORPUS = ROOT / "evals" / "corpus"
EVAL_DIR = ROOT / "local" / "eval"
# The first is seeded by apps/web/e2e/prepare.py --target eval and owns the
# corpus; the second owns nothing, for cases whose honest answer is "you have
# no documents". Both have an email: a user without one is a demo visitor.
OWNER_EMAIL = "eval@example.com"
EMPTY_EMAIL = "eval-empty@example.com"
DEFAULT_MODEL = "claude-haiku-4-5"
# Cases in flight at once: each holds a DB session only briefly and makes a
# few model calls, so four keep well inside the pool and the rate limits
# while cutting a run's wall time about fourfold.
CONCURRENCY = 4
EVAL_DATABASE = "hax_eval"
EVAL_BUCKET = "hax-eval"
MIME = {".md": "text/markdown", ".txt": "text/plain"}


@contextlib.contextmanager
def _acting_as(user_id: uuid.UUID):
    # The identity row-level security reads on every transaction (ADR 0012).
    token = current_user_id.set(user_id)
    try:
        yield
    finally:
        current_user_id.reset(token)


async def setup_users() -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as session:
        owner = await users.get_by_email(session, OWNER_EMAIL)
        if owner is None:
            raise RuntimeError(f"{OWNER_EMAIL} is not seeded: run make eval")
        empty = await users.get_by_email(session, EMPTY_EMAIL)
        if empty is None:
            empty = await users.create_password_user(
                session, EMPTY_EMAIL, hash_password(uuid.uuid4().hex), "Eval empty"
            )
        await session.commit()
        return owner.id, empty.id


async def ingest_corpus(owner: uuid.UUID, corpus: Path) -> None:
    # The prepare step empties the database each run, so every run ingests the
    # corpus once, fresh; objects in hax-eval are keyed by the new ids.
    for path in sorted(p for p in corpus.iterdir() if p.suffix in MIME):
        data = path.read_bytes()
        with _acting_as(owner):
            async with AsyncSessionLocal() as session:
                doc = await documents.create(
                    session,
                    owner,
                    filename=path.name,
                    mime_type=MIME[path.suffix],
                    size_bytes=len(data),
                )
                key = f"documents/{doc.id}/{path.name}"
                await asyncio.to_thread(storage.put, key, data, doc.mime_type)
                doc.storage_key = key
                await session.commit()
                doc_id = doc.id
            await ingest_document_async(doc_id)


async def at_head() -> bool:
    heads = set(
        ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads()
    )
    async with AsyncSessionLocal() as session:
        rows = await session.execute(text("SELECT version_num FROM alembic_version"))
        return {row[0] for row in rows} == heads


async def document_statuses(owner: uuid.UUID) -> list[str]:
    with _acting_as(owner):
        async with AsyncSessionLocal() as session:
            rows = await session.scalars(
                select(Document.status).where(Document.user_id == owner)
            )
            return list(rows)


async def preflight(owner: uuid.UUID, probe_query: str) -> str | None:
    # retrieve() turns every fault into [] so chat never fails on it; without
    # this check a broken stack would grade as a model that never finds
    # anything.
    if not await at_head():
        return "the eval database is not migrated to head"
    statuses = await document_statuses(owner)
    if not statuses:
        return "the eval user has no documents: the corpus was not ingested"
    unready = [s for s in statuses if s != "ready"]
    if unready:
        return f"{len(unready)} of {len(statuses)} corpus documents are not ready"
    with _acting_as(owner):
        if not await retrieve(probe_query, owner):
            return "retrieval returned nothing for the probe query"
    return None


def _score_retrieval(case: Case, chunks: list) -> dict:
    scored: dict = {"nearest_distance": chunks[0].distance if chunks else None}
    passage = case.expect.passage
    if passage is not None:
        rank = hit = None
        for i, chunk in enumerate(chunks, start=1):
            if (
                chunk.filename == passage.document
                and passage.contains.lower() in chunk.content.lower()
            ):
                rank, hit = i, chunk
                break
        scored["expected_passage_rank"] = rank
        scored["distance"] = hit.distance if hit else None
    return scored


# What search_documents tells the model when retrieval returned nothing
# (packages/core/agent/tools.py). retrieve() turns every fault into that, so
# for the corpus owner with no cutoff it means the stack failed, not the model.
NO_PASSAGES = "No relevant passages were found"


def _stack_fault(
    case: Case, results: list[ToolResult], chunks: list | None
) -> str | None:
    if not case.documents or retrieval.MAX_DISTANCE is not None:
        return None
    for r in results:
        # Not is_error: a rejected search is the model's malformed call, which
        # retrieval faults never produce (retrieve() returns [] instead).
        if r["name"] == "search_documents" and r["output"].startswith(NO_PASSAGES):
            return "retrieval returned nothing for the corpus owner: a stack fault"
    if chunks is not None and not chunks:
        return "the retrieval score found nothing for the corpus owner: a stack fault"
    return None


def _total(usages: list[Usage], key: str) -> int:
    return sum(u[key] for u in usages)


async def run_case(case: Case, user_id: uuid.UUID, model: str, judge: Judge) -> dict:
    started = time.monotonic()
    messages: list = [{"role": r, "content": c} for r, c in case.history]
    messages.append({"role": "user", "content": case.question})
    usages: list[Usage] = []
    results: list[ToolResult] = []
    answer: list[str] = []
    passages: list[str] = []
    checks: list[dict] = []
    error = None
    judge_usage: Usage | None = None
    retrieval_score = None
    with _acting_as(user_id):
        try:
            async for event in stream_completion_agentic(
                messages,
                system=member_system(case.note),
                model=model,
                ctx=ToolContext(user_id=user_id),
                on_usage=usages.append,
                on_tool_result=results.append,
            ):
                if "content" in event:
                    answer.append(event["content"])
                elif "sources" in event:
                    passages += [s["excerpt"] for s in event["sources"]]
            text_answer = "".join(answer)
            tools_fired = [r["name"] for r in results]
            checks = [
                {
                    "check": c.check,
                    "pass": c.passed,
                    "detail": c.detail,
                    "reason": c.reason,
                }
                for c in code_checks(case.expect, text_answer, tools_fired)
            ]
            seen = Seen(
                passages=tuple(passages),
                tool_outputs=tuple(r["output"] for r in results),
                note=case.note,
                history=case.history,
            )
            verdict = await judge.grade(
                case.question,
                text_answer,
                case.expect.key_points,
                case.expect.grounded,
                seen,
            )
            judge_usage = verdict.usage
            if verdict.error:
                error = verdict.error
            checks += [
                {
                    "check": c.check,
                    "pass": c.passed,
                    "detail": c.detail,
                    "reason": c.reason,
                }
                for c in verdict.checks
            ]
            chunks = await retrieve(case.question, user_id) if case.documents else None
            if chunks is not None:
                retrieval_score = _score_retrieval(case, chunks)
            # A fault is an error, never a failure: it says nothing about the answer.
            error = error or _stack_fault(case, results, chunks)
        except Exception as exc:  # one broken case must not end the run
            error = f"{type(exc).__name__}: {exc}"
    if error is None and not checks:
        # all([]) would pass any answer: a case that grades nothing is broken.
        error = "the case names nothing to check"
    if error is not None:
        outcome = "error"
    else:
        outcome = "pass" if all(c["pass"] for c in checks) else "fail"
    return {
        "id": case.id,
        "tier": case.tier,
        "tags": list(case.tags),
        "question": case.question,
        "context": {
            "documents": list(case.documents),
            "note": case.note,
            "history": [[r, c] for r, c in case.history],
        },
        "answer": "".join(answer),
        "tools_fired": [r["name"] for r in results],
        "checks": checks,
        "outcome": outcome,
        "error": error,
        "case_hash": case.line_hash,
        "seen": {
            "passages": passages,
            "tool_outputs": [r["output"] for r in results],
            "note": case.note,
        },
        "retrieval": retrieval_score,
        # Every prompt token, cached or not; cost is priced per kind (prices.py).
        "tokens": {
            "in": sum(
                _total(usages, k) for k in ("input", "cache_read", "cache_write")
            ),
            "out": _total(usages, "output"),
        },
        "usd": {
            "model": sum(usd(u) for u in usages),
            "judge": usd(judge_usage) if judge_usage else 0.0,
        },
        "judge_tokens": {
            "in": judge_usage["input"] if judge_usage else 0,
            "out": judge_usage["output"] if judge_usage else 0,
        },
        "seconds": round(time.monotonic() - started, 2),
    }


async def run_cases(
    cases: list[Case],
    owner: uuid.UUID,
    empty: uuid.UUID,
    model: str,
    judge: Judge,
    concurrency: int,
) -> list[dict]:
    gate = asyncio.Semaphore(concurrency)

    async def one(case: Case) -> dict:
        async with gate:
            result = await run_case(
                case, owner if case.documents else empty, model, judge
            )
        print(f"  {result['outcome']:5} {case.id}", flush=True)
        return result

    # gather keeps the cases' order whatever order they finish in.
    return list(await asyncio.gather(*(one(c) for c in cases)))


def concurrency() -> int:
    raw = os.getenv("EVAL_CONCURRENCY")
    if not raw:
        return CONCURRENCY
    # 0 would admit no case and hang the run with the lock held.
    if not raw.isdigit() or int(raw) < 1:
        raise StartError(f"EVAL_CONCURRENCY must be a whole number from 1, not {raw!r}")
    return int(raw)


def exit_code(cases: list[dict]) -> int:
    if any(c["outcome"] == "error" for c in cases):
        return 1
    if any(c["tier"] == "must" and c["outcome"] != "pass" for c in cases):
        return 1
    return 0


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def _cost(cases: list[dict], key: str, tokens: str) -> dict:
    return {
        "in": sum(c[tokens]["in"] for c in cases),
        "out": sum(c[tokens]["out"] for c in cases),
        "usd_estimate": round(sum(c["usd"][key] for c in cases), 4),
    }


class StartError(Exception):
    """The run could not start: nothing was graded (exit 2)."""


def stack_problem(
    database: str | None, bucket: str, endpoint: str | None
) -> str | None:
    # The Makefile points the runner at the eval stack; a bare
    # `python -m evals.run` from the dev shell would otherwise write the corpus
    # into dev's database and bucket, and an unset endpoint is real AWS S3.
    host = urlparse(endpoint or "").hostname
    if (
        database != EVAL_DATABASE
        or bucket != EVAL_BUCKET
        or host not in ("localhost", "127.0.0.1")
    ):
        return (
            f"not the eval stack (database {database}, bucket {bucket}, "
            f"storage {endpoint or 'AWS'}): run it with make eval"
        )
    return None


def _probe_query(cases: list[Case]) -> str:
    for case in cases:
        if case.expect.passage is not None and case.documents:
            return case.question
    return cases[0].question


async def _run(
    cases: list[Case], model: str, judge: AnthropicJudge, in_flight: int
) -> dict:
    started = datetime.now(UTC)
    clock = time.monotonic()
    try:
        owner, empty = await setup_users()
        await ingest_corpus(owner, Path(os.getenv("EVAL_CORPUS") or CORPUS))
        reason = await preflight(owner, _probe_query(cases))
    except Exception as exc:  # Voyage down, the stand-in down, no corpus dir
        raise StartError(f"setup failed: {type(exc).__name__}: {exc}") from exc
    if reason:
        raise StartError(f"preflight: {reason}")
    results = await run_cases(cases, owner, empty, model, judge, in_flight)
    summary = report.summarize(results)
    summary["cost"] = {
        "model": _cost(results, "model", "tokens"),
        "judge": _cost(results, "judge", "judge_tokens"),
    }
    summary["seconds"] = round(time.monotonic() - clock, 1)
    return {
        "run": {
            "started": started.isoformat(timespec="seconds"),
            "commit": _git("rev-parse", "--short", "HEAD"),
            "dirty": bool(_git("status", "--porcelain")),
            "model": model,
            "judge": judge.model,
            "settings": {
                "top_k": retrieval.TOP_K,
                "rag_max_distance": retrieval.MAX_DISTANCE,
            },
            "baseline": None,
        },
        "summary": summary,
        "cases": results,
    }


async def _run_and_close(
    cases: list[Case], model: str, judge: AnthropicJudge, in_flight: int
) -> dict:
    try:
        return await _run(cases, model, judge, in_flight)
    finally:
        # Pooled connections closed inside the loop, not by the collector after.
        await engine.dispose()


def _evaluate() -> int:
    try:
        problem = stack_problem(
            engine.url.database, storage.S3_BUCKET, storage._ENDPOINT_URL
        )
        if problem:
            raise StartError(problem)
        cases = load_cases(Path(os.getenv("EVAL_CASES") or CASES))
        if not cases:
            raise StartError("the case file has no cases")
        in_flight = concurrency()
        judge = AnthropicJudge()
        model = os.getenv("MODEL") or DEFAULT_MODEL
        print(f"eval: {len(cases)} cases, model {model}, judge {judge.model}")
        run = asyncio.run(_run_and_close(cases, model, judge, in_flight))
    except (StartError, CaseFileError, OSError, RuntimeError) as exc:
        print(f"eval: {exc}", file=sys.stderr)
        return 2
    baseline = report.load_baseline(EVAL_DIR / "baseline.json")
    if baseline is not None:
        flips = report.compare(baseline, run)
        run["summary"]["flips"] = {"broke": flips["broke"], "fixed": flips["fixed"]}
        run["run"]["baseline"] = json.loads((EVAL_DIR / "baseline.json").read_text())[
            "run"
        ]
    runs = EVAL_DIR / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now(UTC):%Y-%m-%dT%H-%M-%S}_{run['run']['commit'] or 'nogit'}"
    (runs / f"{stem}.json").write_text(json.dumps(run, indent=2) + "\n")
    (runs / f"{stem}.html").write_text(report.render_html(run))
    print(report.render_terminal(run))
    print(f"wrote {runs / stem}.json and .html")
    return exit_code(run["cases"])


def _set_baseline(name: str) -> int:
    run = EVAL_DIR / "runs" / Path(name).name
    if not run.is_file():
        print(f"eval: no run {run}", file=sys.stderr)
        return 2
    (EVAL_DIR / "baseline.json").write_text(json.dumps({"run": run.name}) + "\n")
    print(f"baseline: {run.name}")
    return 0


def _compare(a: str, b: str) -> int:
    def load(name: str) -> dict:
        path = Path(name)
        if not path.is_file():
            path = EVAL_DIR / "runs" / path.name
        return json.loads(path.read_text())

    result = report.compare(load(a), load(b))
    for key in ("broke", "fixed", "changed", "added", "removed"):
        print(f"{key}: {', '.join(result[key]) or 'none'}")
    for check, delta in result["by_check_delta"].items():
        print(f"  {check} {delta}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="hax eval")
    parser.add_argument("--baseline", metavar="RUN", help="mark a run as baseline")
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"))
    args = parser.parse_args(argv)
    if args.baseline:
        return _set_baseline(args.baseline)
    if args.compare:
        return _compare(*args.compare)
    return _evaluate()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
