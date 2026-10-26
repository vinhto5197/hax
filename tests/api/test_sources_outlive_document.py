"""Sources are a snapshot taken at answer time: deleting the document they
cite must leave the provenance on past replies untouched (ADR 0002)."""

import json

from sqlalchemy import text

from tests.api.conftest import bearer
from tests.api.factories import make_conversation, make_document


async def test_deleting_a_document_keeps_past_sources(
    client, user_a, admin_engine, monkeypatch
):
    from packages.core import storage

    doc = await make_document(
        admin_engine, user_a.id, filename="lease.pdf", storage_key="documents/x/l"
    )
    conv = await make_conversation(admin_engine, user_a.id)
    sources = [
        {
            "document_id": str(doc),
            "filename": "lease.pdf",
            "chunk_idx": 0,
            "excerpt": "one dog allowed",
            "distance": 0.1,
        }
    ]
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO messages (conversation_id, role, content, sources)"
                " VALUES (:cid, 'assistant', 'Yes.', CAST(:sources AS jsonb))"
            ),
            {"cid": conv, "sources": json.dumps(sources)},
        )
    monkeypatch.setattr(storage, "delete", lambda key: None)

    r = await client.delete(f"/api/documents/{doc}", headers=bearer(user_a))
    assert r.status_code == 204

    r = await client.get(f"/api/conversations/{conv}", headers=bearer(user_a))
    assert r.status_code == 200
    [message] = r.json()["messages"]
    assert message["sources"] == sources
