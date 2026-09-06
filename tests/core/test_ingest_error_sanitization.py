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


def test_constraint_violation_message_is_static():
    # Locks the invariant: the chunk-insert IntegrityError handler raises with
    # this exact static text, never an f-string interpolating the raw driver
    # exception (which would leak SQL/params into doc.error on pass-through).
    exc = PermanentIngestError("chunk insert violated a constraint")
    assert _public_error(exc) == "chunk insert violated a constraint"
