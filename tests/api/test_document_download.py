"""GET /api/documents/{id}/download hands its pooled DB connection back before
the (slow, threaded) storage fetch, so a large download cannot pin a
connection for its whole transfer. Ownership and the response shape are
covered in test_authz_documents.py."""

from packages.core import storage
from packages.db import engine as app_engine
from tests.api.conftest import bearer
from tests.api.factories import make_document


async def test_db_connection_is_released_before_the_storage_fetch(
    client, user_a, admin_engine, monkeypatch
):
    # Seeding goes through the admin engine (NullPool), so any checked-out
    # connection on the app pool during the fetch can only be the route's.
    doc = await make_document(
        admin_engine, user_a.id, filename="a.txt", storage_key="documents/x/a.txt"
    )
    seen = []

    def get(key):
        seen.append(app_engine.sync_engine.pool.checkedout())
        return b"payload"

    monkeypatch.setattr(storage, "get", get)

    r = await client.get(f"/api/documents/{doc}/download", headers=bearer(user_a))

    assert r.status_code == 200
    assert r.content == b"payload"
    assert seen == [0]
