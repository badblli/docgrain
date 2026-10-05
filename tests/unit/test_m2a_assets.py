"""Asset retries preserve a verified storage version without rewriting bytes."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from docgrain_worker.canonical_assets import store_asset
from minio.error import S3Error


class Client:
    def __init__(self):
        self.data = None
        self.version = None
        self.puts = 0
        self.released = False

    def stat_object(self, bucket, key):
        if self.data is None:
            raise S3Error(response=None, code="NoSuchKey", message="missing", resource=key,
                          request_id="request", host_id="host")
        return SimpleNamespace(version_id=self.version)

    def put_object(self, bucket, key, stream, length, content_type):
        self.data = stream.read()
        self.version = "immutable-v1"
        self.puts += 1
        return SimpleNamespace(version_id=self.version)

    def get_object(self, bucket, key, *, version_id):
        assert version_id == self.version
        response = BytesIO(self.data)
        def release():
            self.released = True
        response.release_conn = release
        return response


def test_asset_retry_reuses_version_and_fails_on_corrupt_or_unversioned_object():
    client = Client()
    first = store_asset(client, "bucket", "asset", b"PNG", "image/png")
    assert store_asset(client, "bucket", "asset", b"PNG", "image/png") == first
    assert client.puts == 1 and client.released
    client.data = b"corrupt"
    with pytest.raises(ValueError, match="bytes differ"):
        store_asset(client, "bucket", "asset", b"PNG", "image/png")
    assert client.puts == 1
    client.version = "null"
    with pytest.raises(ValueError, match="immutable object version"):
        store_asset(client, "bucket", "asset", b"PNG", "image/png")
