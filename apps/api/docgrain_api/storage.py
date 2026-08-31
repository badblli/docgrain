"""S3-compatible object storage boundary for local MinIO and production providers."""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from .settings import get_settings


def _endpoint(url: str) -> tuple[str, bool]:
    parsed = urlparse(url)
    return parsed.netloc or parsed.path, parsed.scheme == "https"


@lru_cache
def storage_client(*, public: bool = False) -> Minio:
    settings = get_settings()
    endpoint, secure = _endpoint(
        settings.s3_public_endpoint_url if public else settings.s3_endpoint_url
    )
    return Minio(
        endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=secure,
        region="us-east-1",
    )


def presigned_upload_url(object_name: str) -> str:
    settings = get_settings()
    return storage_client(public=True).presigned_put_object(
        settings.s3_bucket,
        object_name,
        expires=timedelta(minutes=15),
    )


def object_exists(object_name: str) -> bool:
    settings = get_settings()
    try:
        storage_client().stat_object(settings.s3_bucket, object_name)
    except S3Error:
        return False
    return True


def put_upload(object_name: str, data: object, content_type: str, length: int) -> None:
    settings = get_settings()
    storage_client().put_object(
        settings.s3_bucket,
        object_name,
        data,
        length=length,
        content_type=content_type,
    )


def get_text(object_name: str) -> str | None:
    """Read a small UTF-8 artifact without exposing object storage to the browser."""
    settings = get_settings()
    try:
        response = storage_client().get_object(settings.s3_bucket, object_name)
    except S3Error:
        return None
    try:
        return response.read().decode("utf-8")
    finally:
        response.close()
        response.release_conn()
