"""Row factories for authz tests. Plain functions over any AsyncEngine — tests
pass the session-scoped admin engine (see conftest: seed as admin `hax`,
exercise routes as `hax_app`).

Raw SQL on purpose: seeding must stay independent of the repo/ORM layer under
test — a repo bug must never be able to seed its own passing data — and the
admin engine deliberately bypasses the app engine's identity machinery."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def make_conversation(
    admin_engine: AsyncEngine, user_id: uuid.UUID, title: str | None = None
) -> uuid.UUID:
    async with admin_engine.begin() as conn:
        row = await conn.execute(
            text(
                "INSERT INTO conversations (user_id, title)"
                " VALUES (:uid, :title) RETURNING id"
            ),
            {"uid": user_id, "title": title},
        )
        return row.scalar_one()


async def make_message(
    admin_engine: AsyncEngine, conversation_id: uuid.UUID, role: str, content: str
) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO messages (conversation_id, role, content)"
                " VALUES (:cid, :role, :content)"
            ),
            {"cid": conversation_id, "role": role, "content": content},
        )


async def make_document(
    admin_engine: AsyncEngine,
    user_id: uuid.UUID,
    filename: str = "doc.txt",
    status: str = "ready",
    storage_key: str | None = None,
) -> uuid.UUID:
    async with admin_engine.begin() as conn:
        row = await conn.execute(
            text(
                "INSERT INTO documents"
                " (user_id, filename, mime_type, size_bytes, status, storage_key)"
                " VALUES (:uid, :fn, 'text/plain', 42, :status, :key) RETURNING id"
            ),
            {"uid": user_id, "fn": filename, "status": status, "key": storage_key},
        )
        return row.scalar_one()


async def make_chunk(
    admin_engine: AsyncEngine,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    idx: int,
    content: str,
    embedding: list[float],
) -> None:
    vec = "[" + ",".join(str(x) for x in embedding) + "]"
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO chunks (document_id, user_id, idx, content, embedding)"
                " VALUES (:did, :uid, :idx, :content, CAST(:vec AS vector))"
            ),
            {
                "did": document_id,
                "uid": user_id,
                "idx": idx,
                "content": content,
                "vec": vec,
            },
        )
