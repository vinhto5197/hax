import uuid

from sqlalchemy import text

from packages.db import AsyncSessionLocal
from packages.db.user_context import current_user_id

GUC = "SELECT current_setting('app.current_user_id', true)"


async def test_transaction_carries_announced_identity():
    uid = uuid.uuid4()
    token = current_user_id.set(uid)
    try:
        async with AsyncSessionLocal() as session:
            value = (await session.execute(text(GUC))).scalar()
    finally:
        current_user_id.reset(token)
    assert value == str(uid)


async def test_unset_context_announces_nothing():
    async with AsyncSessionLocal() as session:
        value = (await session.execute(text(GUC))).scalar()
    assert value in (None, "")  # NULL, or '' once the GUC was ever set locally


async def test_set_local_scope_ends_with_transaction():
    # The pool-bleed fence: identity must NOT survive into the next
    # transaction on the same connection.
    uid = uuid.uuid4()
    token = current_user_id.set(uid)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text(GUC))
            await session.commit()
    finally:
        current_user_id.reset(token)
    async with AsyncSessionLocal() as session:
        value = (await session.execute(text(GUC))).scalar()
    assert value in (None, "")
