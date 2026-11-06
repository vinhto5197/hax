"""search_documents' two empty-handed outcomes stay distinct to the model: a
retrieval outage is an is_error result naming the outage, never the "nothing
found" text; a genuine miss is a normal result with exactly that text. No
database: retrieve is monkeypatched where the tool looks it up."""

from packages.core.agent import tools
from packages.core.agent.harness import _run_tool
from packages.core.rag.retrieval import RetrievalUnavailable

NO_PASSAGES = "No relevant passages were found in the uploaded documents."


async def test_retrieval_outage_is_an_error_result_naming_the_outage(monkeypatch, ctx):
    async def unavailable(query, user_id):
        raise RetrievalUnavailable("document search is temporarily unavailable")

    monkeypatch.setattr(tools, "retrieve", unavailable)

    text, is_error, sources = await _run_tool("search_documents", {"query": "q"}, ctx)

    assert is_error is True
    assert "document search is temporarily unavailable" in text
    assert "No relevant passages" not in text
    assert tuple(sources) == ()


async def test_empty_retrieval_is_a_normal_no_passages_result(monkeypatch, ctx):
    async def nothing(query, user_id):
        return []

    monkeypatch.setattr(tools, "retrieve", nothing)

    text, is_error, sources = await _run_tool("search_documents", {"query": "q"}, ctx)

    assert is_error is False
    assert text == NO_PASSAGES
    assert tuple(sources) == ()
