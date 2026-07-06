"""Object storage (S3 / MinIO) for raw uploaded files.

One boto3 client, configured by env: ``S3_ENDPOINT_URL`` points at MinIO in dev
(``http://localhost:9000``) and is unset in prod, where boto3 uses real AWS S3.
Same dev/prod-parity pattern as Postgres↔RDS — one code path, swapped endpoint.

Shared by the API (writes the raw bytes on upload) and the Celery worker (reads
them on ingest). boto3 is **synchronous**, so async callers (the API routes)
must offload with ``asyncio.to_thread`` — fine here because storage ops are
infrequent (one put per upload), unlike the per-query Voyage embed that earned a
native async client.
"""

import os

import boto3
from botocore.exceptions import ClientError

S3_BUCKET = os.getenv("S3_BUCKET", "hax-documents")
# Unset in prod -> boto3 talks to real AWS S3; set to MinIO's URL in dev.
_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL") or None
_REGION = os.getenv("S3_REGION", "us-east-1")

# Lazy singleton: importing this module never builds a client or needs creds —
# the client is created on first actual use.
_client = None
_bucket_ready = False


class StorageKeyNotFound(Exception):
    """The requested object key does not exist in storage (S3 NoSuchKey).

    Distinct from other storage failures (network blips, 5xx, throttling): a
    missing key is deterministic — S3 is strongly read-after-write consistent, so
    retrying can't make the object appear. Callers can treat it as a permanent
    failure while still retrying the transient ones.
    """


def _get_client():
    global _client
    if _client is None:
        # Credentials come from the env automatically (AWS_ACCESS_KEY_ID /
        # AWS_SECRET_ACCESS_KEY) — MinIO root creds in dev, IAM in prod.
        _client = boto3.client("s3", endpoint_url=_ENDPOINT_URL, region_name=_REGION)
    return _client


def _ensure_bucket() -> None:
    """Create the bucket if it's missing (idempotent), so dev/MinIO works with no
    manual provisioning. In prod the bucket is provisioned by Terraform, but the
    head-then-create is harmless (head succeeds → no-op)."""
    global _bucket_ready
    if _bucket_ready:
        return
    client = _get_client()
    try:
        client.head_bucket(Bucket=S3_BUCKET)
    except ClientError as e:
        # Only a 404 (bucket absent) means "create it". A 403 (bad creds / no
        # permission) or any other error must propagate — masking it as "missing"
        # would blindly attempt a create on, e.g., an auth failure.
        if e.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
        # NOTE (M3): no CreateBucketConfiguration here, so this create only works
        # for us-east-1 + MinIO. us-east-1 is the S3 API's *default* region (you
        # MUST omit LocationConstraint there); any OTHER region REQUIRES
        # CreateBucketConfiguration={"LocationConstraint": _REGION} or it 400s —
        # it does NOT fall back to us-east-1. Harmless today: prod's bucket is
        # Terraform-provisioned, so head_bucket succeeds and this never runs.
        client.create_bucket(Bucket=S3_BUCKET)
    _bucket_ready = True


def put(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Write bytes to object storage under ``key``. Blocking — offload from the
    event loop with ``asyncio.to_thread``."""
    _ensure_bucket()
    _get_client().put_object(
        Bucket=S3_BUCKET, Key=key, Body=data, ContentType=content_type
    )


def get(key: str) -> bytes:
    """Read the bytes stored under ``key``. Blocking.

    Raises ``StorageKeyNotFound`` if the object is missing; other storage errors
    (5xx, throttling, network) propagate as botocore ``ClientError`` for the
    caller to treat as transient.
    """
    try:
        return _get_client().get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            raise StorageKeyNotFound(key) from exc
        raise


def delete(key: str) -> None:
    """Delete the object at ``key`` (no error if it's already gone). Blocking."""
    _get_client().delete_object(Bucket=S3_BUCKET, Key=key)
