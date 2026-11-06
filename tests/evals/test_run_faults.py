"""The eval runner treats a retrieval outage as a stack fault, not as the
agent's miss: _stack_fault flags a search_documents error naming the outage
(and only that error), and preflight turns a RetrievalUnavailable probe into
a stop reason instead of a crash. Probes monkeypatched; no database."""

import uuid

from evals import run
from evals.cases import Case, Expect

from packages.core.agent.harness import ToolResult
from packages.core.rag.retrieval import RetrievalUnavailable, RetrievedChunk

USER = uuid.UUID("11111111-1111-1111-1111-111111111111")
OUTAGE = "document search is temporarily unavailable"


def _documents_case() -> Case:
    return Case(
        id="rent",
        tier="must",
        tags=("rag", "money"),
        question="What is my rent?",
        documents=("lease.md",),
        note=None,
        history=(),
        expect=Expect(contains_none=("zzz",)),
        line_hash="abc123def456",
    )


def _search_error(output: str) -> ToolResult:
    return ToolResult(
        name="search_documents",
        input={"query": "rent"},
        output=output,
        is_error=True,
    )


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        content="Rent is $2,000 a month.",
        filename="lease.md",
        distance=0.2,
        document_id=uuid.uuid4(),
        chunk_idx=0,
    )


def test_search_outage_result_is_a_stack_fault():
    results = [_search_error(f"Error running search_documents: {OUTAGE}")]

    fault = run._stack_fault(_documents_case(), results, [_chunk()])

    assert isinstance(fault, str) and fault


def test_malformed_search_call_error_is_not_a_stack_fault():
    results = [
        _search_error("Error running search_documents: 1 validation error for ...")
    ]

    assert run._stack_fault(_documents_case(), results, [_chunk()]) is None


async def test_preflight_reports_retrieval_unavailable_instead_of_raising(
    monkeypatch,
):
    async def at_head():
        return True

    async def document_statuses(owner):
        return ["ready", "ready"]

    async def retrieve(query, user_id, *args, **kwargs):
        raise RetrievalUnavailable(OUTAGE)

    monkeypatch.setattr(run, "at_head", at_head)
    monkeypatch.setattr(run, "document_statuses", document_statuses)
    monkeypatch.setattr(run, "retrieve", retrieve)

    reason = await run.preflight(USER, "rent")

    assert isinstance(reason, str) and reason
