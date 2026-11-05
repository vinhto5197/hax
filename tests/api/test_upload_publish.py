"""An accepted upload publishes `ingest_document` with the new document's id
and the uploading user's id: the worker announces that user for RLS, so a
wrong or missing id would ingest under another identity or under none."""

from apps.worker.tasks import ingest_document
from tests.api.conftest import bearer


async def test_an_accepted_upload_publishes_ingest_with_the_uploaders_id(
    client, user_a, stub_storage, published
):
    r = await client.post(
        "/api/documents",
        files={"file": ("mine.txt", b"hello world", "text/plain")},
        headers=bearer(user_a),
    )
    assert r.status_code == 200, r.text
    ingests = [args for name, args in published if name == ingest_document.name]
    assert ingests == [(r.json()["id"], str(user_a.id))]
