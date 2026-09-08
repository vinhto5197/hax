"""Cross-cutting authz sweep (M2.5 slice 2, Task 6): the ingest-ownership
regression owed since slice-2 DB fixtures landed, the agent tool-context path
end to end, GUC-less fail-closed checks, and the raise-site sanitization lock
for the chunk-insert IntegrityError path (Step 1b — supersedes the tautological
unit test in tests/core/test_ingest_error_sanitization.py).

Two distinct isolation layers are exercised on purpose, never blended within
one assertion:
  - layer 1 (app-level WHERE / ToolContext.user_id) — proven by running
    against a superuser session (RLS out) so only the app filter can produce
    the result, same idiom as tests/api/test_authz_retrieval.py.
  - layer 2 (RLS, via the announced GUC) — proven by the worker/route
    contract: current_user_id.set() around the one real entry point that
    contract governs (ingest_document_async here), never around a direct
    retrieve()/tool call, which layer 1's tests deliberately run unannounced.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.core.agent.tools import (
    SEARCH_DOCUMENTS,
    SearchDocumentsInput,
    ToolContext,
)
from packages.core.rag.ingest import PermanentIngestError
from packages.db.user_context import current_user_id
from tests.api.factories import make_document

DIM = 1024


def unit_vec(hot: int) -> list[float]:
    v = [0.0] * DIM
    v[hot] = 1.0
    return v


async def test_ingest_inherits_owner_and_stays_partitioned(
    user_a, user_b, admin_engine, monkeypatch
):
    # The banked regression (backlog: "ingest regression test owed when
    # slice-2 DB fixtures land"): chunks inherit doc.user_id through the real
    # worker code path, announced-identity included.
    from packages.core import storage
    from packages.core.rag import ingest, retrieval

    doc_id = await make_document(
        admin_engine, user_a.id, status="pending", storage_key="documents/x/a.md"
    )
    monkeypatch.setattr(storage, "get", lambda key: b"alpha secret " * 40)

    async def fake_embed_documents(chunks: list[str]) -> list[list[float]]:
        return [unit_vec(0) for _ in chunks]

    monkeypatch.setattr(ingest, "embed_documents", fake_embed_documents)

    token = current_user_id.set(user_a.id)  # the worker contract (tasks.py)
    try:
        await ingest.ingest_document_async(doc_id)
    finally:
        current_user_id.reset(token)

    async with admin_engine.begin() as conn:
        owners = (
            (
                await conn.execute(
                    text("SELECT DISTINCT user_id FROM chunks WHERE document_id = :d"),
                    {"d": doc_id},
                )
            )
            .scalars()
            .all()
        )
    assert owners == [user_a.id]

    async def fake_embed_query(query: str) -> list[float]:
        return unit_vec(0)

    monkeypatch.setattr(retrieval, "embed_query", fake_embed_query)
    # RLS would mask a dropped app-level WHERE (same partition, different
    # layer); run as superuser so only retrieve()'s user_id filter can
    # produce this result — no current_user_id announcement here.
    monkeypatch.setattr(
        retrieval,
        "AsyncSessionLocal",
        async_sessionmaker(admin_engine, expire_on_commit=False),
    )
    assert await retrieval.retrieve("alpha", user_b.id) == []
    assert await retrieval.retrieve("alpha", user_a.id) != []


async def test_agent_search_respects_tool_context(
    user_a, user_b, admin_engine, monkeypatch
):
    # The executor the model actually calls, under B's context, over A's corpus.
    from packages.core.rag import retrieval
    from tests.api.factories import make_chunk

    a_doc = await make_document(admin_engine, user_a.id)
    await make_chunk(admin_engine, a_doc, user_a.id, 0, "alpha secret", unit_vec(0))

    async def fake_embed_query(query: str) -> list[float]:
        return unit_vec(0)

    monkeypatch.setattr(retrieval, "embed_query", fake_embed_query)
    # superuser session: RLS out, so ToolContext is the only thing scoping this.
    monkeypatch.setattr(
        retrieval,
        "AsyncSessionLocal",
        async_sessionmaker(admin_engine, expire_on_commit=False),
    )

    out_b = await SEARCH_DOCUMENTS.run(
        SearchDocumentsInput(query="alpha"), ToolContext(user_id=user_b.id)
    )
    assert "alpha secret" not in out_b

    out_a = await SEARCH_DOCUMENTS.run(
        SearchDocumentsInput(query="alpha"), ToolContext(user_id=user_a.id)
    )
    assert "alpha secret" in out_a


async def test_guc_less_document_and_chunk_queries_empty(user_a, admin_engine):
    from sqlalchemy import func, select

    from packages.db import AsyncSessionLocal
    from packages.db.models import Chunk, Document
    from tests.api.factories import make_chunk

    doc_id = await make_document(admin_engine, user_a.id)
    await make_chunk(admin_engine, doc_id, user_a.id, 0, "x", unit_vec(1))
    async with AsyncSessionLocal() as session:
        docs = await session.scalar(select(func.count()).select_from(Document))
        chunks = await session.scalar(select(func.count()).select_from(Chunk))
    assert (docs, chunks) == (0, 0)


async def test_constraint_violation_message_is_static(
    user_a, admin_engine, monkeypatch
):
    # Locks ingest.py's IntegrityError handler: driver text (which carries
    # [SQL: ...] [parameters: ...]) must never reach the PermanentIngestError
    # message — it becomes user-visible doc.error via _public_error.
    #
    # Hermetic by construction (gate ruling 2026-09-06, replacing an earlier
    # delete-mid-ingest attempt that empirically hit StaleDataError on the
    # Document status UPDATE before ever reaching the chunk-insert
    # IntegrityError — see task-6-report.md): patch AsyncSession.commit to
    # let ingest's first commit (status="processing") through untouched, then
    # raise a real IntegrityError carrying driver-shaped leak bait in place of
    # its second commit (status="ready" + chunk insert), independent of
    # SQLAlchemy's flush-ordering behavior.
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import AsyncSession

    from packages.core import storage
    from packages.core.rag import ingest

    doc_id = await make_document(
        admin_engine, user_a.id, status="pending", storage_key="documents/x/a.md"
    )
    monkeypatch.setattr(storage, "get", lambda key: b"alpha secret " * 40)

    async def fake_embed_documents(chunks):
        return [unit_vec(0) for _ in chunks]

    monkeypatch.setattr(ingest, "embed_documents", fake_embed_documents)

    real_commit = AsyncSession.commit
    commits = 0

    async def commit_then_violate(self):
        nonlocal commits
        commits += 1
        if commits == 2:  # 1st = status->processing; 2nd = chunk insert + ready
            raise IntegrityError(
                "INSERT INTO chunks (content, embedding) VALUES (%s, %s)",
                {"content": "LEAKED-CHUNK-TEXT", "embedding": "[0.1, ...]"},
                Exception("duplicate key value violates unique constraint"),
            )
        return await real_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", commit_then_violate)

    token = current_user_id.set(user_a.id)  # the worker contract (tasks.py)
    try:
        with pytest.raises(PermanentIngestError) as excinfo:
            await ingest.ingest_document_async(doc_id)
    finally:
        current_user_id.reset(token)

    message = str(excinfo.value)
    assert message == "chunk insert violated a constraint"
    assert "LEAKED-CHUNK-TEXT" not in message and "[SQL" not in message
