import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from packages.db import AsyncSessionLocal
from packages.db.models import Conversation, Message
from packages.db.user_context import current_user_id
from tests.api.factories import make_conversation, make_message


async def test_guc_less_connection_sees_zero_rows(user_a, admin_engine):
    # THE fail-closed acceptance check: a code path that forgot to announce
    # identity gets nothing — not everything.
    await make_conversation(admin_engine, user_a.id)
    async with AsyncSessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(Conversation))
    assert count == 0


async def test_rls_filters_a_deliberately_unscoped_query(user_a, user_b, admin_engine):
    # Simulates the "future code path forgets the WHERE" bug: no app-level
    # filter at all, RLS alone must partition.
    a_conv = await make_conversation(admin_engine, user_a.id)
    await make_conversation(admin_engine, user_b.id)
    token = current_user_id.set(user_a.id)
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.scalars(select(Conversation))).all()
    finally:
        current_user_id.reset(token)
    assert [c.id for c in rows] == [a_conv]


async def test_rls_blocks_write_with_foreign_owner(user_a, user_b):
    # WITH CHECK: announced as A, inserting a row owned by B must be refused.
    token = current_user_id.set(user_a.id)
    try:
        with pytest.raises(DBAPIError):
            async with AsyncSessionLocal() as session:
                session.add(Conversation(user_id=user_b.id))
                await session.commit()
    finally:
        current_user_id.reset(token)


async def test_messages_follow_their_conversations_owner(user_a, user_b, admin_engine):
    a_conv = await make_conversation(admin_engine, user_a.id)
    await make_message(admin_engine, a_conv, "user", "secret")
    token = current_user_id.set(user_b.id)
    try:
        async with AsyncSessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == a_conv)
            )
    finally:
        current_user_id.reset(token)
    assert count == 0


async def test_message_insert_into_foreign_conversation_rejected(
    user_a, user_b, admin_engine
):
    # WITH CHECK on messages: B cannot write into A's thread even with a
    # deliberately unscoped insert — the EXISTS subquery sees no owned parent.
    a_conv = await make_conversation(admin_engine, user_a.id)
    token = current_user_id.set(user_b.id)
    try:
        with pytest.raises(DBAPIError):
            async with AsyncSessionLocal() as session:
                session.add(
                    Message(conversation_id=a_conv, role="user", content="intrusion")
                )
                await session.commit()
    finally:
        current_user_id.reset(token)


async def test_users_table_reachable_without_identity(user_a):
    # No RLS on users (signup/login run pre-identity); regression guard.
    async with AsyncSessionLocal() as session:
        value = await session.scalar(
            text("SELECT count(*) FROM users WHERE email = 'a@test.local'")
        )
    assert value == 1
