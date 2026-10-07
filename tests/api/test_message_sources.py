"""messages.sources: nullable JSONB written by add_message, read back as-is."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.db.repos import conversations as repo
from tests.api.factories import make_conversation

SOURCES = [
    {
        "document_id": "00000000-0000-0000-0000-00000000d0c1",
        "filename": "lease.pdf",
        "chunk_idx": 0,
        "excerpt": "one dog allowed",
        "distance": 0.1,
    }
]


async def test_add_message_persists_sources(admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    Session = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with Session() as session:
        await repo.add_message(session, conv, "assistant", "Yes.", sources=SOURCES)
        await session.commit()
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT sources FROM messages WHERE conversation_id = :c"),
                {"c": conv},
            )
        ).scalar_one()
    assert row == SOURCES


async def test_add_message_default_is_null(admin_engine, user_a):
    conv = await make_conversation(admin_engine, user_a.id)
    Session = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with Session() as session:
        await repo.add_message(session, conv, "user", "dog?")
        await session.commit()
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                # SQL NULL, not the JSON value 'null' (asyncpg decodes both to
                # None, so only the predicate can tell them apart).
                text("SELECT sources IS NULL FROM messages WHERE conversation_id = :c"),
                {"c": conv},
            )
        ).scalar_one()
    assert row is True
