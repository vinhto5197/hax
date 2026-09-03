import uuid

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


async def test_chat_append_to_foreign_conversation_404(
    client, user_a, user_b, admin_engine
):
    # The write half of Task 14's finding: B must not add turns to A's thread.
    # persist_user_turn 404s before any LLM call, so no network is touched.
    a_conv = await make_conversation(admin_engine, user_a.id)
    r = await client.post(
        "/api/chat",
        json={"prompt": "hi", "conversation_id": str(a_conv)},
        headers=bearer(user_b),
    )
    assert r.status_code == 404
