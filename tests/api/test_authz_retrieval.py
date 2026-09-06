from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.core.rag import retrieval
from tests.api.factories import make_chunk, make_document

DIM = 1024


def unit_vec(hot: int) -> list[float]:
    v = [0.0] * DIM
    v[hot] = 1.0
    return v


async def test_retrieval_is_partitioned(user_a, user_b, admin_engine, monkeypatch):
    a_doc = await make_document(admin_engine, user_a.id, filename="a.md")
    await make_chunk(admin_engine, a_doc, user_a.id, 0, "alpha secret", unit_vec(0))
    # B needs a ready chunk of their own too — otherwise retrieve()'s
    # no-ready-chunk-for-this-user pre-check (a second, earlier user_id
    # filter) short-circuits B's call to [] before the main query ever runs,
    # and the assertion below would pass even if the main query's user_id
    # filter were deleted. A different vector keeps it out of A's top-k.
    b_doc = await make_document(admin_engine, user_b.id, filename="b.md")
    await make_chunk(admin_engine, b_doc, user_b.id, 0, "beta secret", unit_vec(1))

    async def fake_embed_query(query: str) -> list[float]:
        return unit_vec(0)  # identical to A's chunk -> distance 0

    monkeypatch.setattr(retrieval, "embed_query", fake_embed_query)
    # RLS would mask a dropped app-level WHERE (same partition, different
    # layer); run as superuser so only the app filter can produce this result.
    monkeypatch.setattr(
        retrieval,
        "AsyncSessionLocal",
        async_sessionmaker(admin_engine, expire_on_commit=False),
    )

    hits_a = await retrieval.retrieve("alpha", user_a.id)
    assert [c.content for c in hits_a] == ["alpha secret"]

    hits_b = await retrieval.retrieve("alpha", user_b.id)
    assert [c.content for c in hits_b] == ["beta secret"]


async def test_no_corpus_for_user_skips_embed(
    user_a, user_b, admin_engine, monkeypatch
):
    a_doc = await make_document(admin_engine, user_a.id)
    await make_chunk(admin_engine, a_doc, user_a.id, 0, "alpha", unit_vec(0))

    # A raising fake would be swallowed by retrieve()'s degrade-to-[] except;
    # a call flag survives it.
    called = False

    async def spy_embed(query: str) -> list[float]:
        nonlocal called
        called = True
        return unit_vec(0)

    monkeypatch.setattr(retrieval, "embed_query", spy_embed)
    # Same reasoning as above: superuser session isolates the app-level WHERE
    # from RLS, so this test's zero-rows outcome is proof of the skip-embed
    # branch, not a side effect of no identity being announced.
    monkeypatch.setattr(
        retrieval,
        "AsyncSessionLocal",
        async_sessionmaker(admin_engine, expire_on_commit=False),
    )

    assert await retrieval.retrieve("anything", user_b.id) == []
    assert called is False
