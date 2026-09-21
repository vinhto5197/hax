"""Layer-1 proof for the title repo functions: over a superuser session RLS
cannot answer for the user_id predicates."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.db.repos import conversations as conversations_repo
from tests.api.factories import make_conversation, make_message


async def _row(admin_engine, conv_id):
    async with admin_engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT title, updated_at FROM conversations WHERE id = :i"),
                {"i": conv_id},
            )
        ).one()


async def test_first_user_message_skips_later_and_assistant_turns(user_a, admin_engine):
    conv = await make_conversation(admin_engine, user_a.id)
    # An assistant turn seeded first: if the role filter were ever dropped,
    # ordering by created_at alone would return this row instead.
    await make_message(admin_engine, conv, "assistant", "opening note")
    await make_message(admin_engine, conv, "user", "first question")
    await make_message(admin_engine, conv, "assistant", "first answer")
    await make_message(admin_engine, conv, "user", "second question")
    factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with factory() as session:
        got = await conversations_repo.first_user_message(session, user_a.id, conv)
    assert got == "first question"


async def test_first_user_message_none_when_empty(user_a, admin_engine):
    conv = await make_conversation(admin_engine, user_a.id)
    factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with factory() as session:
        assert (
            await conversations_repo.first_user_message(session, user_a.id, conv)
            is None
        )


async def test_first_user_message_is_owner_scoped(user_a, user_b, admin_engine):
    conv = await make_conversation(admin_engine, user_a.id)
    await make_message(admin_engine, conv, "user", "a's question")
    factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with factory() as session:
        assert (
            await conversations_repo.first_user_message(session, user_b.id, conv)
            is None
        )


async def test_set_title_if_unset_writes_once_and_keeps_order(user_a, admin_engine):
    conv = await make_conversation(admin_engine, user_a.id)
    before = (await _row(admin_engine, conv)).updated_at
    factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with factory() as session:
        assert await conversations_repo.set_title_if_unset(
            session, user_a.id, conv, "First"
        )
        assert not await conversations_repo.set_title_if_unset(
            session, user_a.id, conv, "Second"
        )
        await session.commit()
    row = await _row(admin_engine, conv)
    assert row.title == "First"
    assert row.updated_at == before  # a title write must not reorder the sidebar


async def test_set_title_if_unset_is_owner_scoped(user_a, user_b, admin_engine):
    conv = await make_conversation(admin_engine, user_a.id)
    factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with factory() as session:
        assert not await conversations_repo.set_title_if_unset(
            session, user_b.id, conv, "Nope"
        )
        await session.commit()
    assert (await _row(admin_engine, conv)).title is None
