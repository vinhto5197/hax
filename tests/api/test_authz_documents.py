from types import SimpleNamespace

from tests.api.conftest import bearer
from tests.api.factories import make_document


async def test_list_is_partitioned(client, user_a, user_b, admin_engine):
    a_doc = await make_document(admin_engine, user_a.id, filename="a.txt")
    await make_document(admin_engine, user_b.id, filename="b.txt")
    r = await client.get("/api/documents", headers=bearer(user_a))
    assert r.status_code == 200
    assert [d["id"] for d in r.json()] == [str(a_doc)]


async def test_delete_foreign_document_404_and_survives(
    client, user_a, user_b, admin_engine
):
    a_doc = await make_document(admin_engine, user_a.id)
    r = await client.delete(f"/api/documents/{a_doc}", headers=bearer(user_b))
    assert r.status_code == 404
    still = await client.get("/api/documents", headers=bearer(user_a))
    assert [d["id"] for d in still.json()] == [str(a_doc)]


async def test_owner_delete_204(client, user_a, admin_engine, monkeypatch):
    from packages.core import storage

    a_doc = await make_document(
        admin_engine, user_a.id, storage_key="documents/x/a.txt"
    )
    monkeypatch.setattr(storage, "delete", lambda key: None)
    r = await client.delete(f"/api/documents/{a_doc}", headers=bearer(user_a))
    assert r.status_code == 204


async def test_upload_stamps_owner(client, user_a, admin_engine, monkeypatch):
    from sqlalchemy import text

    import apps.api.routers.documents as documents_router
    from packages.core import storage

    monkeypatch.setattr(storage, "put", lambda key, content, mime: None)
    monkeypatch.setattr(
        documents_router,
        "ingest_document",
        SimpleNamespace(delay=lambda *args: None),
    )
    r = await client.post(
        "/api/documents",
        files={"file": ("mine.txt", b"hello world", "text/plain")},
        headers=bearer(user_a),
    )
    assert r.status_code == 200
    async with admin_engine.begin() as conn:
        owner = (
            await conn.execute(
                text("SELECT user_id FROM documents WHERE id = :id"),
                {"id": r.json()["id"]},
            )
        ).scalar_one()
    assert owner == user_a.id
