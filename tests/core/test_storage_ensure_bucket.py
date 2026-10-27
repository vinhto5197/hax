"""_ensure_bucket creates the bucket when head_bucket says 404, and treats a
create that loses a race (the bucket now exists, ours or not) as success, so
two processes starting together both come up. Any other create failure
propagates and leaves the bucket unconfirmed. The boto3 client is faked."""

import pytest
from botocore.exceptions import ClientError

from packages.core import storage


def _client_error(code: str, status: int, op: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "m"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        op,
    )


class FakeClient:
    def __init__(self, create_error: ClientError | None = None):
        self.create_error = create_error
        self.head_calls: list[dict] = []
        self.create_calls: list[dict] = []

    def head_bucket(self, **kwargs):
        self.head_calls.append(kwargs)
        raise _client_error("404", 404, "HeadBucket")

    def create_bucket(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.create_error is not None:
            raise self.create_error
        return {}


@pytest.fixture
def fake_client(monkeypatch):
    def install(create_error: ClientError | None = None) -> FakeClient:
        client = FakeClient(create_error)
        monkeypatch.setattr(storage, "_get_client", lambda: client)
        monkeypatch.setattr(storage, "_bucket_ready", False)
        return client

    return install


def test_missing_bucket_is_created(fake_client):
    client = fake_client()

    storage._ensure_bucket()

    assert client.head_calls == [{"Bucket": storage.S3_BUCKET}]
    assert client.create_calls == [{"Bucket": storage.S3_BUCKET}]
    assert storage._bucket_ready is True


@pytest.mark.parametrize("code", ["BucketAlreadyOwnedByYou", "BucketAlreadyExists"])
def test_losing_the_create_race_counts_as_ready(fake_client, code):
    client = fake_client(_client_error(code, 409, "CreateBucket"))

    storage._ensure_bucket()

    assert len(client.create_calls) == 1
    assert storage._bucket_ready is True


def test_unrelated_create_error_propagates(fake_client):
    fake_client(_client_error("AccessDenied", 403, "CreateBucket"))

    with pytest.raises(ClientError) as excinfo:
        storage._ensure_bucket()

    assert excinfo.value.response["Error"]["Code"] == "AccessDenied"
    assert storage._bucket_ready is False


def test_ready_bucket_is_not_checked_again(fake_client, monkeypatch):
    client = fake_client()
    monkeypatch.setattr(storage, "_bucket_ready", True)

    storage._ensure_bucket()

    assert client.head_calls == []
    assert client.create_calls == []
