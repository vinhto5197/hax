"""The search tool's two outputs: text for the model (byte-identical to the
pre-sources format) and sources for the user. Every other tool keeps
returning a plain string."""

import uuid

from packages.core.agent import tools
from packages.core.agent.tools import (
    SEARCH_DOCUMENTS,
    SearchDocumentsInput,
    Source,
    ToolContext,
    ToolOutput,
)
from packages.core.rag.retrieval import RetrievedChunk

DOC = uuid.UUID("00000000-0000-0000-0000-00000000d0c1")


def _chunk(idx: int, content: str, distance: float) -> RetrievedChunk:
    return RetrievedChunk(
        content=content,
        filename="lease.pdf",
        distance=distance,
        document_id=DOC,
        chunk_idx=idx,
    )


async def test_search_returns_text_and_sources(monkeypatch):
    async def fake_retrieve(query, user_id):
        return [_chunk(0, "one dog allowed", 0.1), _chunk(2, "deposit $300", 0.3)]

    monkeypatch.setattr(tools, "retrieve", fake_retrieve)
    out = await SEARCH_DOCUMENTS.run(
        SearchDocumentsInput(query="dog"), ToolContext(user_id=uuid.uuid4())
    )
    assert isinstance(out, ToolOutput)
    assert out.text == (
        "[1] from lease.pdf:\none dog allowed\n\n[2] from lease.pdf:\ndeposit $300"
    )
    assert out.sources == (
        Source(DOC, "lease.pdf", 0, "one dog allowed", 0.1),
        Source(DOC, "lease.pdf", 2, "deposit $300", 0.3),
    )


async def test_empty_search_returns_plain_string(monkeypatch):
    async def fake_retrieve(query, user_id):
        return []

    monkeypatch.setattr(tools, "retrieve", fake_retrieve)
    out = await SEARCH_DOCUMENTS.run(
        SearchDocumentsInput(query="dog"), ToolContext(user_id=uuid.uuid4())
    )
    assert out == "No relevant passages were found in the uploaded documents."


def test_source_as_dict_is_json_safe():
    d = Source(DOC, "lease.pdf", 2, "deposit $300", 0.3).as_dict()
    assert d == {
        "document_id": str(DOC),
        "filename": "lease.pdf",
        "chunk_idx": 2,
        "excerpt": "deposit $300",
        "distance": 0.3,
    }


async def test_other_tools_still_return_str():
    from packages.core.agent.tools import CalculatorInput, _run_calculator

    out = await _run_calculator(
        CalculatorInput(expression="1 + 1"), ToolContext(user_id=uuid.uuid4())
    )
    assert isinstance(out, str)
