import pytest
from fastapi import HTTPException

from apps.api.auth import internal_only


async def test_correct_secret_passes(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SECRET", "s3cret")
    assert await internal_only("s3cret") is None


async def test_wrong_secret_404(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SECRET", "s3cret")
    with pytest.raises(HTTPException) as exc_info:
        await internal_only("wrong")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Not Found"


async def test_non_ascii_header_is_404_not_typeerror(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SECRET", "s3cret")
    with pytest.raises(HTTPException) as exc_info:
        await internal_only("café")
    assert exc_info.value.status_code == 404


async def test_unset_secret_rejects_even_matching_empty_header(monkeypatch):
    monkeypatch.delenv("INTERNAL_API_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        await internal_only("")
    assert exc_info.value.status_code == 404
