import json
import uuid

from sqlalchemy import text

from tests.api.conftest import bearer
from tests.api.factories import make_conversation, make_message


async def test_list_is_partitioned(client, user_a, user_b, admin_engine):
    a_conv = await make_conversation(admin_engine, user_a.id, title="a's")
    await make_conversation(admin_engine, user_b.id, title="b's")
    r = await client.get("/api/conversations", headers=bearer(user_a))
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == [str(a_conv)]


async def test_get_foreign_conversation_404(client, user_a, user_b, admin_engine):
    a_conv = await make_conversation(admin_engine, user_a.id)
    await make_message(admin_engine, a_conv, "user", "secret")
    r = await client.get(f"/api/conversations/{a_conv}", headers=bearer(user_b))
    assert r.status_code == 404


async def test_foreign_and_nonexistent_404s_are_identical(
    client, user_a, user_b, admin_engine
):
    # Ownership miss must not confirm existence: byte-identical to a miss.
    a_conv = await make_conversation(admin_engine, user_a.id)
    foreign = await client.get(f"/api/conversations/{a_conv}", headers=bearer(user_b))
    missing = await client.get(
        f"/api/conversations/{uuid.uuid4()}", headers=bearer(user_b)
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


async def test_owner_get_200_with_messages(client, user_a, admin_engine):
    a_conv = await make_conversation(admin_engine, user_a.id)
    await make_message(admin_engine, a_conv, "user", "hello")
    r = await client.get(f"/api/conversations/{a_conv}", headers=bearer(user_a))
    assert r.status_code == 200
    assert [m["content"] for m in r.json()["messages"]] == ["hello"]


async def test_delete_foreign_conversation_404_and_survives(
    client, user_a, user_b, admin_engine
):
    a_conv = await make_conversation(admin_engine, user_a.id)
    r = await client.delete(f"/api/conversations/{a_conv}", headers=bearer(user_b))
    assert r.status_code == 404
    still = await client.get(f"/api/conversations/{a_conv}", headers=bearer(user_a))
    assert still.status_code == 200


async def test_owner_delete_204(client, user_a, admin_engine):
    a_conv = await make_conversation(admin_engine, user_a.id)
    r = await client.delete(f"/api/conversations/{a_conv}", headers=bearer(user_a))
    assert r.status_code == 204
    gone = await client.get(f"/api/conversations/{a_conv}", headers=bearer(user_a))
    assert gone.status_code == 404


async def test_chat_append_to_foreign_conversation_404(
    client, user_a, user_b, admin_engine
):
    # The write half of isolation: B must not append turns to A's thread;
    # persist_user_turn 404s before any LLM call, so no network is touched.
    a_conv = await make_conversation(admin_engine, user_a.id)
    r = await client.post(
        "/api/chat",
        json={"prompt": "hi", "conversation_id": str(a_conv)},
        headers=bearer(user_b),
    )
    assert r.status_code == 404


SRC = {
    "document_id": "00000000-0000-0000-0000-00000000d0c1",
    "filename": "lease.pdf",
    "chunk_idx": 0,
    "excerpt": "one dog allowed",
    "distance": 0.1,
}


async def _insert_assistant_with_sources(admin_engine, conv_id, sources):
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO messages (conversation_id, role, content, sources)"
                " VALUES (:c, 'assistant', 'Yes.', CAST(:s AS jsonb))"
            ),
            {"c": conv_id, "s": json.dumps(sources)},
        )


async def test_detail_returns_sources(client, user_a, admin_engine):
    conv = await make_conversation(admin_engine, user_a.id)
    await make_message(admin_engine, conv, "user", "dog?")
    await _insert_assistant_with_sources(admin_engine, conv, [SRC])
    r = await client.get(f"/api/conversations/{conv}", headers=bearer(user_a))
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert msgs[0]["sources"] is None
    assert msgs[1]["sources"] == [SRC]


async def test_detail_returns_sources_after_document_delete(
    client, user_a, admin_engine
):
    # Provenance is a snapshot: the row references no document, so deleting
    # (or never having had) the document leaves it intact.
    conv = await make_conversation(admin_engine, user_a.id)
    await _insert_assistant_with_sources(admin_engine, conv, [SRC])
    r = await client.get(f"/api/conversations/{conv}", headers=bearer(user_a))
    assert r.json()["messages"][0]["sources"][0]["filename"] == "lease.pdf"
