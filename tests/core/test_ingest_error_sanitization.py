from apps.worker.tasks import GENERIC_INGEST_ERROR, _public_error
from packages.core.rag.ingest import PermanentIngestError


def test_permanent_errors_pass_through():
    exc = PermanentIngestError("document produced no chunks after splitting")
    assert _public_error(exc) == "document produced no chunks after splitting"


def test_transient_errors_are_masked():
    exc = RuntimeError("VoyageError: 401 at https://internal/key=sk-abc123")
    out = _public_error(exc)
    assert out == GENERIC_INGEST_ERROR
    assert "sk-abc123" not in out
