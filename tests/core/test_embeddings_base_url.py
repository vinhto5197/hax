"""The Voyage client honours VOYAGE_BASE_URL, the e2e stack's seam to its fake
embeddings endpoint; unset or empty, the SDK picks its own default. The module
caches its client, so every case resets the cache first."""

import pytest

from packages.core.rag import embeddings

FAKE_URL = "http://localhost:8787/v1"
SDK_DEFAULT = "https://api.voyageai.com/v1"


@pytest.fixture(autouse=True)
def fresh_client(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-test-key")
    monkeypatch.setattr(embeddings, "_client", None)
    yield
    embeddings._client = None


def _base_url(client) -> str | None:
    return client._params["base_url"]


def test_voyage_base_url_set_points_the_client_at_it(monkeypatch):
    monkeypatch.setenv("VOYAGE_BASE_URL", FAKE_URL)

    assert _base_url(embeddings._get_client()) == FAKE_URL


def test_voyage_base_url_unset_leaves_the_sdk_default(monkeypatch):
    monkeypatch.delenv("VOYAGE_BASE_URL", raising=False)

    assert _base_url(embeddings._get_client()) == SDK_DEFAULT


def test_voyage_base_url_empty_leaves_the_sdk_default(monkeypatch):
    monkeypatch.setenv("VOYAGE_BASE_URL", "")

    assert _base_url(embeddings._get_client()) == SDK_DEFAULT
