"""Verified review outputs and one SQL transaction for revision/head/publication.

Object uploads are staged first. SQL visibility is atomic; orphaned immutable
objects after a failed CAS are safe to reuse but are not visible publications.
"""

from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
from urllib.parse import parse_qs, urlparse

from docgrain_domain.canonical.ai_output import MIME, OutputFile, OutputPublication, output_bundle
from docgrain_domain.canonical.identity import canonical_json_bytes
from docgrain_domain.canonical.review import build_review_revision
from docgrain_domain.storage_paths import source_version_id
from minio.error import S3Error
from psycopg.errors import UniqueViolation

from .canonical_repository import CanonicalConflict, CanonicalRepository
from .output_repository import OutputRepository


class StorageIntegrityError(ValueError):
    """Pinned storage bytes or immutable location failed verification."""


def verified_bytes(client, bucket, uri, checksum, size):
    parsed = urlparse(uri)
    versions = parse_qs(parsed.query).get("versionId", [])
    if parsed.scheme != "s3" or parsed.netloc != bucket or len(versions) != 1 or versions[0] == "null":
        raise StorageIntegrityError("immutable in-bucket object version required")
    response = client.get_object(bucket, parsed.path.lstrip("/"), version_id=versions[0])
    try:
        data = response.read()
    finally:
        response.close()
        response.release_conn()
    if len(data) != size or sha256(data).hexdigest() != checksum:
        raise StorageIntegrityError("source/asset/output checksum differs from pinned bytes")
    return data


def verified_source(client, bucket, snapshot):
    source = snapshot.source_version
    parsed = urlparse(source.storage_uri)
    versions = parse_qs(parsed.query).get("versionId", [])
    if (
        parsed.scheme != "s3" or parsed.netloc != bucket
        or source_version_id(source.storage_uri, snapshot.workspace_id, snapshot.document_id) is None
        or len(versions) != 1 or versions[0] != source.storage_version
    ):
        raise StorageIntegrityError("source object outside document/version scope")
    return verified_bytes(client, bucket, source.storage_uri, source.content_sha256, source.byte_size)


def _store_file(client, bucket, key, data, mime):
    try:
        stat = client.stat_object(bucket, key)
    except S3Error as exc:
        if exc.code not in {"NoSuchKey", "NoSuchObject"}:
            raise
        stored = client.put_object(bucket, key, BytesIO(data), len(data), content_type=mime)
        version = stored.version_id
    else:
        version = stat.version_id
    if not version or version == "null":
        raise StorageIntegrityError("output has no immutable storage version")
    uri = f"s3://{bucket}/{key}?versionId={version}"
    verified_bytes(client, bucket, uri, sha256(data).hexdigest(), len(data))
    return uri


def _stage_outputs(client, bucket, snapshot):
    verified_source(client, bucket, snapshot)
    for artifact in snapshot.artifacts:
        verified_bytes(client, bucket, artifact.storage_uri, artifact.content_sha256, artifact.byte_size)
    _, chunks, revision, files = output_bundle(snapshot)
    prefix = f"knowledge/{snapshot.document_id}/{snapshot.knowledge_revision.id}/{revision.id}"
    stored = []
    for name, data in files.items():
        uri = _store_file(client, bucket, f"{prefix}/{name}", data, MIME[name])
        stored.append(OutputFile(name=name, content_sha256=sha256(data).hexdigest(),
                                 byte_size=len(data), mime_type=MIME[name], storage_uri=uri))
    return chunks, OutputPublication(revision=revision, files=stored)


def save_review(repository, base, request, client, bucket):
    """No parser, provider, embedding or approval-pointer mutation."""
    candidate = build_review_revision(base, request)
    existing = repository.find_review_operation(base.document_id, request.operation_id)
    if existing is not None:
        if canonical_json_bytes(existing.model_dump(mode="json")) != canonical_json_bytes(candidate.model_dump(mode="json")):
            raise CanonicalConflict("operation ID already has another review payload")
        publication = OutputRepository(repository._connect, repository._schema).get_outputs(existing.knowledge_revision.id)
        if publication is None:
            raise CanonicalConflict("existing review has no committed output publication")
        return existing, False
    heads = repository.get_heads(base.document_id)
    if heads is None or heads[0] != base.knowledge_revision.id:
        raise CanonicalConflict("latest head changed; reload the document before saving")
    chunks, publication = _stage_outputs(client, bucket, candidate)
    try:
        with repository._connect() as connection:
            # These contexts borrow the transaction; they never commit or close it.
            @contextmanager
            def shared_connection():
                yield connection

            transaction_repo = CanonicalRepository(shared_connection, repository._schema)
            inserted = transaction_repo.append(candidate, expected_latest_revision_id=base.knowledge_revision.id)
            outputs = OutputRepository(shared_connection, repository._schema)
            if not inserted:
                committed = outputs.get_outputs(candidate.knowledge_revision.id)
                if committed is None:
                    raise CanonicalConflict("replayed review lacks committed outputs")
            else:
                if chunks.chunks:
                    transaction_repo.append_derived(chunks.manifest())
                outputs.publish_outputs(publication)
    except UniqueViolation as exc:
        raise CanonicalConflict("review operation ID changed concurrently") from exc
    return candidate, inserted
