"""Object storage (S3 / MinIO) for raw uploaded files.

``S3_ENDPOINT_URL`` points at MinIO in dev and is unset in prod (real AWS S3) —
one code path, swapped endpoint. boto3 is synchronous: async callers must
offload with ``asyncio.to_thread``.
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
    """Object key absent (S3 NoSuchKey) — deterministic, unlike transient
    storage failures, so callers can treat it as permanent."""


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
        # Only a 404 means "create it"; a 403 (bad creds) must propagate.
        if e.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
        # No CreateBucketConfiguration -> only valid for us-east-1/MinIO (other
        # regions 400 without a LocationConstraint). Fine: prod buckets are
        # Terraform-provisioned, so this create never runs there.
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
