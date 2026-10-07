"""The harness's third event: {"sources": [...]} after a tool that returned
ToolOutput, with only the text sent back to the model. Scripted fake client;
no network."""

import uuid
from types import SimpleNamespace

import pytest

from packages.core.agent import harness, tools
from packages.core.agent.tools import Source, ToolContext, ToolOutput

DOC = uuid.UUID("00000000-0000-0000-0000-00000000d0c1")
SRC = Source(DOC, "lease.pdf", 0, "one dog allowed", 0.1)


class _Stream:
    def __init__(self, turn):
        self._turn = turn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    async def text_stream(self):
        for t in self._turn["text"]:
            yield t

    async def get_final_message(self):
        return SimpleNamespace(
            content=self._turn["content"],
            stop_reason=self._turn["stop_reason"],
            usage=SimpleNamespace(
                input_tokens=1,
                output_tokens=1,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )


class FakeClient:
    """Each call to messages.stream consumes the next scripted turn and
    records the kwargs it was called with."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return _Stream(self.turns.pop(0))


def tool_use(name, inp, id_="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=inp, id=id_)


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def search_turn():
    return {
        "text": [],
        "content": [tool_use("search_documents", {"query": "dog"})],
        "stop_reason": "tool_use",
    }


def answer_turn(text="Yes, one dog."):
    return {"text": [text], "content": [text_block(text)], "stop_reason": "end_turn"}


def patch_search(monkeypatch, run):
    # SEARCH_DOCUMENTS is frozen; swap the registry entry the harness reads.
    monkeypatch.setitem(
        tools.TOOLS,
        "search_documents",
        tools.Tool(
            name="search_documents",
            description="x",
            label="Searching documents…",
            input_model=tools.SearchDocumentsInput,
            run=run,
        ),
    )


@pytest.fixture
def ctx():
    return ToolContext(user_id=uuid.uuid4())


async def _collect(gen):
    return [e async for e in gen]


async def test_tool_output_yields_sources_and_sends_only_text(monkeypatch, ctx):
    async def fake_search(inp, c):
        return ToolOutput(text="[1] from lease.pdf:\none dog allowed", sources=(SRC,))

    patch_search(monkeypatch, fake_search)
    client = FakeClient([search_turn(), answer_turn()])
    monkeypatch.setattr(harness, "_client", client)

    events = await _collect(
        harness.stream_completion_agentic(
            [{"role": "user", "content": "dog?"}], ctx=ctx
        )
    )
    assert events == [
        {"status": "Searching documents…"},
        {"sources": [SRC.as_dict()]},
        {"content": "Yes, one dog."},
    ]
    # Only the text reached the model: the tool_result block carries no sources.
    second_call = client.calls[1]["messages"]
    result_turn = second_call[-1]
    [block] = result_turn["content"]
    assert block["type"] == "tool_result"
    assert block["content"] == "[1] from lease.pdf:\none dog allowed"
    assert block["is_error"] is False
    assert "sources" not in block


async def test_str_tool_yields_no_sources(monkeypatch, ctx):
    async def fake_search(inp, c):
        return "No relevant passages were found in the uploaded documents."

    patch_search(monkeypatch, fake_search)
    client = FakeClient([search_turn(), answer_turn("Nothing found.")])
    monkeypatch.setattr(harness, "_client", client)

    events = await _collect(
        harness.stream_completion_agentic(
            [{"role": "user", "content": "dog?"}], ctx=ctx
        )
    )
    assert events == [
        {"status": "Searching documents…"},
        {"content": "Nothing found."},
    ]


async def test_tool_error_yields_no_sources(monkeypatch, ctx):
    async def boom(inp, c):
        raise RuntimeError("voyage down")

    patch_search(monkeypatch, boom)
    client = FakeClient([search_turn(), answer_turn("Could not search.")])
    monkeypatch.setattr(harness, "_client", client)

    events = await _collect(
        harness.stream_completion_agentic(
            [{"role": "user", "content": "dog?"}], ctx=ctx
        )
    )
    assert {"status": "Searching documents…"} in events
    assert not any("sources" in e for e in events)
    [block] = client.calls[1]["messages"][-1]["content"]
    assert block["is_error"] is True


async def test_tools_false_never_yields_sources(monkeypatch, ctx):
    client = FakeClient([answer_turn("Hello.")])
    monkeypatch.setattr(harness, "_client", client)

    events = await _collect(
        harness.stream_completion_agentic(
            [{"role": "user", "content": "hi"}], ctx=ctx, tools=False
        )
    )
    assert events == [{"content": "Hello."}]
    assert "tools" not in client.calls[0]


async def test_sources_survive_the_max_iters_fallback(monkeypatch, ctx):
    async def fake_search(inp, c):
        return ToolOutput(text="[1] from lease.pdf:\none dog allowed", sources=(SRC,))

    patch_search(monkeypatch, fake_search)
    turns = [search_turn() for _ in range(harness.MAX_ITERS)] + [answer_turn("Forced.")]
    client = FakeClient(turns)
    monkeypatch.setattr(harness, "_client", client)

    events = await _collect(
        harness.stream_completion_agentic(
            [{"role": "user", "content": "dog?"}], ctx=ctx
        )
    )
    assert events.count({"sources": [SRC.as_dict()]}) == harness.MAX_ITERS
    assert events[-1] == {"content": "Forced."}
    assert "tools" not in client.calls[-1]
