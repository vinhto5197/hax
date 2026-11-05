class PermanentIngestError(Exception):
    """A deterministic ingestion failure that retrying cannot fix, such as a
    missing document or file, unreadable or over-budget content, or an unusable
    embedding response.

    The Celery task records the document 'failed' immediately on this, instead of
    retrying. Any OTHER exception (Voyage / S3 / DB I/O) is treated as transient
    and retried with backoff.

    Messages are USER-VISIBLE (doc.error via the task's _public_error): static
    text only — never ids, filenames or raw driver/SDK text.
    """
