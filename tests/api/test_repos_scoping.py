"""Layer-1 proof for packages.db.repos (AR-2026-09-08 #4): exercised over an
async_sessionmaker(admin_engine) session — a superuser connection RLS cannot
answer for — so only the repo's own user_id predicates can produce a
correctly scoped result; route-level tests alone cannot detect a dropped
WHERE because RLS silently produces the same partition.
"""

from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.db.repos import conversations as conversations_repo
from packages.db.repos import documents as documents_repo
from tests.api.factories import make_conversation, make_document, make_message


async def test_conversations_list_for_user_excludes_other_user(
    user_a, user_b, admin_engine
):
    await make_conversation(admin_engine, user_a.id)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        rows = await conversations_repo.list_for_user(session, user_b.id)
    assert rows == []


async def test_conversations_get_owned_excludes_other_user(
    user_a, user_b, admin_engine
):
    a_conv = await make_conversation(admin_engine, user_a.id)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await conversations_repo.get_owned(session, user_b.id, a_conv)
    assert result is None


async def test_conversations_delete_owned_excludes_other_user(
    user_a, user_b, admin_engine
):
    a_conv = await make_conversation(admin_engine, user_a.id)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        deleted = await conversations_repo.delete_owned(session, user_b.id, a_conv)
        await session.commit()
    assert deleted is False

    async with session_factory() as session:
        survivor = await conversations_repo.get_owned(session, user_a.id, a_conv)
    assert survivor is not None


async def test_conversations_load_history_excludes_other_user(
    user_a, user_b, admin_engine
):
    a_conv = await make_conversation(admin_engine, user_a.id)
    await make_message(admin_engine, a_conv, "user", "alpha secret")
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        history = await conversations_repo.load_history(session, user_b.id, a_conv)
    assert history == []


async def test_documents_list_for_user_excludes_other_user(
    user_a, user_b, admin_engine
):
    await make_document(admin_engine, user_a.id)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        rows = await documents_repo.list_for_user(session, user_b.id)
    assert rows == []


async def test_documents_get_owned_excludes_other_user(user_a, user_b, admin_engine):
    a_doc = await make_document(admin_engine, user_a.id)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await documents_repo.get_owned(session, user_b.id, a_doc)
    assert result is None


async def test_documents_delete_owned_excludes_other_user(user_a, user_b, admin_engine):
    a_doc = await make_document(admin_engine, user_a.id)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        deleted = await documents_repo.delete_owned(session, user_b.id, a_doc)
        await session.commit()
    assert deleted is None

    async with session_factory() as session:
        survivor = await documents_repo.get_owned(session, user_a.id, a_doc)
    assert survivor is not None
