"""Reuse verified immutable asset objects when a parsing event is replayed."""

from hashlib import sha256
from io import BytesIO

from minio.error import S3Error


def store_asset(client, bucket: str, key: str, data: bytes, mime_type: str) -> str:
    try:
        stat = client.stat_object(bucket, key)
    except S3Error as exc:
        if exc.code not in {"NoSuchKey", "NoSuchObject"}:
            raise
        stored = client.put_object(bucket, key, BytesIO(data), len(data), content_type=mime_type)
        version = stored.version_id
    else:
        version = stat.version_id
        if not version or version == "null":
            raise ValueError("extracted asset has no immutable object version")
        response = client.get_object(bucket, key, version_id=version)
        try:
            if sha256(response.read()).digest() != sha256(data).digest():
                raise ValueError("existing content-addressed asset bytes differ")
        finally:
            response.close()
            response.release_conn()
    if not version or version == "null":
        raise ValueError("extracted asset has no immutable object version")
    return f"s3://{bucket}/{key}?versionId={version}"
