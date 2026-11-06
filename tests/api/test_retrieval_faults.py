"""retrieve()'s failure contract: an embedding or database fault after the
readiness check surfaces as RetrievalUnavailable with a fixed, content-free
message (never the original exception's text, in the error or in the
WARNING-and-above logs); a user with no ready chunk still gets [] without an
embed. Real Postgres (tests/api fixtures), embed monkeypatched."""

import logging

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.core.rag import retrieval
from tests.api.factories import make_chunk, make_document, unit_vec

MESSAGE = "document search is temporarily unavailable"


async def _seed_ready_chunk(admin_engine, user):
    doc = await make_document(admin_engine, user.id, filename="a.md")
    await make_chunk(admin_engine, doc, user.id, 0, "alpha secret", unit_vec(0))


def _admin_sessions(admin_engine):
    return async_sessionmaker(admin_engine, expire_on_commit=False)


def _raising_embed(exc: BaseException):
    calls: list[str] = []

    async def embed(query: str) -> list[float]:
        calls.append(query)
        raise exc

    return embed, calls


async def test_embed_failure_raises_retrieval_unavailable_with_fixed_message(
    user_a, admin_engine, monkeypatch
):
    await _seed_ready_chunk(admin_engine, user_a)
    embed, calls = _raising_embed(RuntimeError("voyage exploded"))
    monkeypatch.setattr(retrieval, "embed_query", embed)
    monkeypatch.setattr(retrieval, "AsyncSessionLocal", _admin_sessions(admin_engine))

    with pytest.raises(retrieval.RetrievalUnavailable) as info:
        await retrieval.retrieve("alpha", user_a.id)

    assert calls == ["alpha"]
    assert str(info.value) == MESSAGE


@pytest.mark.parametrize(
    "exc",
    [ValueError("bad"), TimeoutError(), ConnectionError("refused"), KeyError("k")],
)
async def test_any_embed_exception_becomes_retrieval_unavailable(
    exc, user_a, admin_engine, monkeypatch
):
    await _seed_ready_chunk(admin_engine, user_a)
    embed, _ = _raising_embed(exc)
    monkeypatch.setattr(retrieval, "embed_query", embed)
    monkeypatch.setattr(retrieval, "AsyncSessionLocal", _admin_sessions(admin_engine))

    with pytest.raises(retrieval.RetrievalUnavailable) as info:
        await retrieval.retrieve("alpha", user_a.id)

    assert str(info.value) == MESSAGE


async def test_database_failure_after_embed_raises_retrieval_unavailable(
    user_a, admin_engine, monkeypatch
):
    await _seed_ready_chunk(admin_engine, user_a)
    real_sessions = _admin_sessions(admin_engine)
    opened = 0
    embedded = False

    async def boom(*args, **kwargs):
        raise RuntimeError("search query failed")

    def sessions(*args, **kwargs):
        # The first session is the readiness check; every session opened
        # after the embed fails on its first query.
        nonlocal opened
        opened += 1
        session = real_sessions(*args, **kwargs)
        if embedded:
            for name in ("execute", "scalars", "scalar", "stream", "stream_scalars"):
                setattr(session, name, boom)
        return session

    async def embed(query: str) -> list[float]:
        nonlocal embedded
        embedded = True
        return unit_vec(0)

    monkeypatch.setattr(retrieval, "embed_query", embed)
    monkeypatch.setattr(retrieval, "AsyncSessionLocal", sessions)

    with pytest.raises(retrieval.RetrievalUnavailable) as info:
        await retrieval.retrieve("alpha", user_a.id)

    assert embedded is True
    assert opened >= 2
    assert str(info.value) == MESSAGE


async def test_embed_failure_text_never_reaches_warning_logs_or_the_error(
    user_a, admin_engine, monkeypatch, caplog
):
    await _seed_ready_chunk(admin_engine, user_a)
    embed, _ = _raising_embed(RuntimeError("SECRET-QUERY-TEXT"))
    monkeypatch.setattr(retrieval, "embed_query", embed)
    monkeypatch.setattr(retrieval, "AsyncSessionLocal", _admin_sessions(admin_engine))
    caplog.set_level(logging.DEBUG)

    with pytest.raises(retrieval.RetrievalUnavailable) as info:
        await retrieval.retrieve("alpha", user_a.id)

    assert "SECRET-QUERY-TEXT" not in str(info.value)
    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    formatter = logging.Formatter()
    # format() includes any attached traceback, which would carry the text.
    assert all("SECRET-QUERY-TEXT" not in formatter.format(r) for r in loud)
    assert any("RuntimeError" in r.getMessage() for r in loud)


async def test_user_without_ready_chunks_gets_empty_list_and_no_embed(
    user_a, user_b, admin_engine, monkeypatch
):
    await _seed_ready_chunk(admin_engine, user_a)
    embed, calls = _raising_embed(RuntimeError("must not be called"))
    monkeypatch.setattr(retrieval, "embed_query", embed)
    monkeypatch.setattr(retrieval, "AsyncSessionLocal", _admin_sessions(admin_engine))

    assert await retrieval.retrieve("anything", user_b.id) == []
    assert calls == []
