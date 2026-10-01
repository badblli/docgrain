"""Explicit complete scans; notifications trigger scans and are never source authority."""

import hashlib
from pathlib import Path

from docgrain_domain.canonical.live_sources import SourceObservation


class IncompleteObservation(RuntimeError):
    """A partial scan must never advance a connector cursor or imply deletion."""


def _stamp(path: Path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class FilesystemSource:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("source root must be directory")

    def _inventory(self):
        # Path.rglob may suppress traversal errors; use os.walk with an explicit failure callback.
        import os

        def fail(error):
            raise error

        files = {}
        if not self.root.is_dir():
            raise IncompleteObservation("source root unavailable")
        for folder, dirs, names in os.walk(self.root, onerror=fail, followlinks=False):
            for name in dirs + names:
                path = Path(folder) / name
                if path.is_symlink():
                    raise IncompleteObservation("symlink in source tree")
            for name in names:
                path = Path(folder) / name
                if path.suffix.lower() not in {".pdf", ".docx", ".xlsx", ".txt"}:
                    continue
                path.resolve(strict=True).relative_to(self.root)
                files[path.relative_to(self.root).as_posix()] = _stamp(path)
        return files

    def read(self, observation: SourceObservation) -> bytes:
        path = self.root / observation.source_key
        path.resolve(strict=True).relative_to(self.root)
        if path.is_symlink():
            raise IncompleteObservation("symlink source")
        before = _stamp(path)
        data = path.read_bytes()
        if (before != _stamp(path) or len(data) != observation.byte_size
                or hashlib.sha256(data).hexdigest() != observation.content_sha256):
            raise IncompleteObservation("source changed since observation")
        return data

    def scan(self) -> dict[str, SourceObservation]:
        try:
            inventory = self._inventory()
            observations = {}
            for key, stamp in sorted(inventory.items()):
                path = self.root / key
                data = path.read_bytes()
                if stamp != _stamp(path):
                    raise IncompleteObservation("source changed during scan")
                digest = hashlib.sha256(data).hexdigest()
                observations[key] = SourceObservation(source_key=key, uri=path.as_uri(),
                                                      version=digest, content_sha256=digest, byte_size=len(data))
            if inventory != self._inventory():
                raise IncompleteObservation("source tree changed during scan")
            return observations
        except (OSError, ValueError) as error:
            raise IncompleteObservation("filesystem scan incomplete") from error


class ObjectStoreSource:
    """Versioned MinIO/S3; double listing rejects observed concurrent changes.

    Multi-object listing is not an atomic S3 snapshot. Repeated reconciliation is
    eventually consistent; production needs notification delivery + periodic rescans.
    """

    def __init__(self, client, bucket: str, prefix: str = ""):
        self.client, self.bucket, self.prefix = client, bucket, prefix

    def _inventory(self):
        return {o.object_name: (o.etag, o.size, int(o.last_modified.timestamp()))
                for o in self.client.list_objects(self.bucket, prefix=self.prefix, recursive=True)
                if Path(o.object_name).suffix.lower() in {".pdf", ".docx", ".xlsx", ".txt"}}

    def read(self, observation: SourceObservation) -> bytes:
        if not observation.source_key.startswith(self.prefix):
            raise ValueError("object outside connector prefix")
        response = self.client.get_object(self.bucket, observation.source_key, version_id=observation.version)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
        if len(data) != observation.byte_size or hashlib.sha256(data).hexdigest() != observation.content_sha256:
            raise IncompleteObservation("object content mismatch")
        return data

    def scan(self) -> dict[str, SourceObservation]:
        try:
            inventory = self._inventory()
            observations = {}
            for key, stamp in sorted(inventory.items()):
                stat = self.client.stat_object(self.bucket, key)
                if (stat.etag, stat.size, int(stat.last_modified.timestamp())) != stamp:
                    raise IncompleteObservation("object changed during scan")
                if not stat.version_id or stat.version_id == "null":
                    raise IncompleteObservation("versioned object required")
                response = self.client.get_object(self.bucket, key, version_id=stat.version_id)
                try:
                    data = response.read()
                finally:
                    response.close()
                    response.release_conn()
                if len(data) != stat.size:
                    raise IncompleteObservation("object size mismatch")
                observations[key] = SourceObservation(source_key=key, uri=f"s3://{self.bucket}/{key}",
                    version=stat.version_id, content_sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data))
            if inventory != self._inventory():
                raise IncompleteObservation("object listing changed during scan")
            return observations
        except IncompleteObservation:
            raise
        except Exception as error:
            raise IncompleteObservation("object scan incomplete") from error
