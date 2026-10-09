from types import SimpleNamespace

import pytest

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
    still = await client.get("/api/documents", headers=bearer(user_a))
    assert str(a_doc) not in [d["id"] for d in still.json()]


async def test_upload_stamps_owner(client, user_a, admin_engine, monkeypatch):
    from sqlalchemy import text

    import apps.api.routers.documents as documents_router
    from packages.core import storage

    monkeypatch.setattr(storage, "put", lambda key, content, mime: None)
    monkeypatch.setattr(
        documents_router,
        "ingest_document",
        SimpleNamespace(name="ingest_document", apply_async=lambda args, retry: None),
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


async def test_upload_marks_failed_when_the_broker_is_down(
    client, user_a, admin_engine, monkeypatch
):
    # 'pending' must always mean a task is really queued, so the upload route
    # awaits its publish and records the outage on the row.
    import apps.api.routers.documents as documents_router
    from packages.core import storage

    def unreachable(args, retry):
        raise OSError("broker down")

    monkeypatch.setattr(storage, "put", lambda key, content, mime: None)
    monkeypatch.setattr(
        documents_router,
        "ingest_document",
        SimpleNamespace(name="ingest_document", apply_async=unreachable),
    )
    r = await client.post(
        "/api/documents",
        files={"file": ("mine.txt", b"hello world", "text/plain")},
        headers=bearer(user_a),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    assert r.json()["error"] == "could not start ingestion (task queue unavailable)"


@pytest.fixture
def stub_publish(monkeypatch):
    import apps.api.routers.documents as documents_router
    from packages.core import storage

    monkeypatch.setattr(storage, "put", lambda key, content, mime: None)
    monkeypatch.setattr(
        documents_router,
        "ingest_document",
        SimpleNamespace(name="ingest_document", apply_async=lambda args, retry: None),
    )


async def test_upload_accepts_pdf_without_parsing_it(client, user_a, stub_publish):
    # Binary formats are parsed only in the worker: the route stores whatever
    # bytes carry the suffix and lets ingestion report an unreadable file.
    r = await client.post(
        "/api/documents",
        files={"file": ("report.pdf", b"%PDF-1.4 not really", "application/pdf")},
        headers=bearer(user_a),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


async def test_upload_rejects_unknown_suffix(client, user_a, stub_publish):
    r = await client.post(
        "/api/documents",
        files={"file": ("tool.exe", b"MZ", "application/octet-stream")},
        headers=bearer(user_a),
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "supported files: .txt, .md, .pdf, .docx"


async def test_upload_rejects_pdf_over_5mb_on_declared_length(
    client, user_a, stub_publish
):
    # httpx keeps a caller-set Content-Length, so the route sees a declared
    # 5 MB + 1 and refuses before reading the (tiny) body.
    r = await client.post(
        "/api/documents",
        files={"file": ("big.pdf", b"%PDF-1.4", "application/pdf")},
        headers={**bearer(user_a), "content-length": str(5 * 1024 * 1024 + 1)},
    )
    assert r.status_code == 413
    assert r.json()["detail"] == "file exceeds 5120 KB"


async def test_upload_rejects_text_over_256kb(client, user_a, stub_publish):
    r = await client.post(
        "/api/documents",
        files={"file": ("big.txt", b"a" * (256 * 1024 + 1), "text/plain")},
        headers=bearer(user_a),
    )
    assert r.status_code == 413
    assert r.json()["detail"] == "file exceeds 256 KB"


async def test_listing_fails_documents_stuck_in_flight_past_the_deadline(
    client, user_a, user_b, admin_engine
):
    from sqlalchemy import text

    stale = await make_document(admin_engine, user_a.id, status="processing")
    fresh = await make_document(admin_engine, user_a.id, status="processing")
    theirs = await make_document(admin_engine, user_b.id, status="processing")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE documents SET updated_at = now() - interval '2 hours'"
                " WHERE id IN (:a, :b)"
            ),
            {"a": stale, "b": theirs},
        )

    r = await client.get("/api/documents", headers=bearer(user_a))
    assert r.status_code == 200
    by_id = {d["id"]: d for d in r.json()}
    assert by_id[str(stale)]["status"] == "failed"
    assert "upload the file again" in by_id[str(stale)]["error"]
    assert by_id[str(fresh)]["status"] == "processing"

    # Another user's stale row is untouched: the deadline runs as the caller.
    async with admin_engine.connect() as conn:
        status = (
            await conn.execute(
                text("SELECT status FROM documents WHERE id = :i"), {"i": theirs}
            )
        ).scalar_one()
    assert status == "processing"


async def test_owner_download_returns_the_stored_bytes(
    client, user_a, admin_engine, monkeypatch
):
    from packages.core import storage

    a_doc = await make_document(
        admin_engine, user_a.id, filename="a.txt", storage_key="documents/x/a.txt"
    )
    monkeypatch.setattr(storage, "get", lambda key: b"hello world")
    r = await client.get(f"/api/documents/{a_doc}/download", headers=bearer(user_a))
    assert r.status_code == 200
    assert r.content == b"hello world"
    assert r.headers["content-type"] == "text/plain"
    assert r.headers["content-disposition"].startswith("attachment;")
    assert "a.txt" in r.headers["content-disposition"]


async def test_download_foreign_document_404_without_touching_storage(
    client, user_a, user_b, admin_engine, monkeypatch
):
    from packages.core import storage

    a_doc = await make_document(
        admin_engine, user_a.id, storage_key="documents/x/a.txt"
    )
    touched = []
    monkeypatch.setattr(storage, "get", lambda key: touched.append(key) or b"")
    r = await client.get(f"/api/documents/{a_doc}/download", headers=bearer(user_b))
    assert r.status_code == 404
    assert touched == []


async def test_download_without_stored_bytes_404(
    client, user_a, admin_engine, monkeypatch
):
    # A row whose put never succeeded has no storage_key: same answer as a miss.
    from packages.core import storage

    a_doc = await make_document(admin_engine, user_a.id, storage_key=None)
    touched = []
    monkeypatch.setattr(storage, "get", lambda key: touched.append(key) or b"")
    r = await client.get(f"/api/documents/{a_doc}/download", headers=bearer(user_a))
    assert r.status_code == 404
    assert r.json()["detail"] == "document not found"
    assert touched == []


async def test_download_filename_cannot_inject_a_header(
    client, user_a, admin_engine, monkeypatch
):
    from packages.core import storage

    a_doc = await make_document(
        admin_engine,
        user_a.id,
        filename='evil"\r\nX-Injected: 1.txt',
        storage_key="documents/x/evil.txt",
    )
    monkeypatch.setattr(storage, "get", lambda key: b"x")
    r = await client.get(f"/api/documents/{a_doc}/download", headers=bearer(user_a))
    assert r.status_code == 200
    assert "x-injected" not in r.headers
    cd = r.headers["content-disposition"]
    assert "\r" not in cd and "\n" not in cd
    fallback = cd.split('filename="', 1)[1].split('"; filename*=', 1)[0]
    assert '"' not in fallback
    assert fallback == "evil_X-Injected: 1.txt"
    assert cd.endswith("filename*=UTF-8''evil%22%0D%0AX-Injected%3A%201.txt")


async def test_visitor_cannot_download(client, user_a, admin_engine, monkeypatch):
    from packages.core import storage
    from tests.api.factories import make_visitor

    visitor = await make_visitor(admin_engine)
    a_doc = await make_document(
        admin_engine, visitor.id, storage_key="documents/x/a.txt"
    )
    touched = []
    monkeypatch.setattr(storage, "get", lambda key: touched.append(key) or b"")
    r = await client.get(
        f"/api/documents/{a_doc}/download", headers=bearer(visitor, anonymous=True)
    )
    assert r.status_code == 403
    assert r.json()["detail"] == {"code": "demo_limit"}
    assert touched == []


async def test_download_of_a_missing_object_is_a_404(
    client, user_a, admin_engine, monkeypatch
):
    from packages.core import storage

    doc = await make_document(admin_engine, user_a.id, storage_key="documents/x/a.txt")

    def gone(key):
        raise storage.StorageKeyNotFound(key)

    monkeypatch.setattr(storage, "get", gone)
    r = await client.get(f"/api/documents/{doc}/download", headers=bearer(user_a))
    assert r.status_code == 404
