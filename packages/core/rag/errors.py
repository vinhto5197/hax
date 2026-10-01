class PermanentIngestError(Exception):
    """A deterministic ingestion failure that retrying cannot fix — missing doc,
    missing storage_key, the object absent from storage, unreadable content
    (bad UTF-8, an unparseable or text-less PDF/DOCX), or no chunks after
    splitting.

    The Celery task records the document 'failed' immediately on this, instead of
    retrying. Any OTHER exception (Voyage / S3 / DB I/O) is treated as transient
    and retried with backoff.

    Messages are USER-VISIBLE (they become doc.error via the task's _public_error
    pass-through): keep them static or interpolate only server-generated ids/
    filenames — never raw driver/SDK exception text.
    """
