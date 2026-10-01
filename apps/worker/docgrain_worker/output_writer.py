"""Write-time automatic output publication, without parser/model work on read paths."""

from hashlib import sha256
from urllib.parse import parse_qs, urlparse

from docgrain_api.output_repository import OutputRepository
from docgrain_domain.canonical.ai_output import MIME, OutputFile, OutputPublication, output_bundle

from .canonical_assets import store_asset


def verified_object(client, bucket, uri, checksum, size):
    parsed = urlparse(uri)
    versions = parse_qs(parsed.query).get("versionId", [])
    if parsed.scheme != "s3" or parsed.netloc != bucket or len(versions) != 1 or versions[0] == "null":
        raise ValueError("immutable in-bucket object version required")
    response = client.get_object(bucket,parsed.path.lstrip("/"),version_id=versions[0])
    try:
        data = response.read()
    finally:
        response.close()
        response.release_conn()
    if len(data) != size or sha256(data).hexdigest() != checksum:
        raise ValueError("stored output/source/asset bytes fail checksum")
    return data


def publish_outputs(repository, snapshot, client, bucket):
    """Caller verified source; assets and every stored output are checked before pointer commit."""
    output, chunks, revision, files = output_bundle(snapshot)
    for asset in snapshot.artifacts:
        verified_object(client,bucket,asset.storage_uri,asset.content_sha256,asset.byte_size)
    prefix = f"knowledge/{snapshot.document_id}/{snapshot.knowledge_revision.id}/{revision.id}"
    stored = []
    for name,data in files.items():
        uri = store_asset(client,bucket,f"{prefix}/{name}",data,MIME[name])
        checksum = sha256(data).hexdigest()
        verified_object(client,bucket,uri,checksum,len(data))
        stored.append(OutputFile(name=name,content_sha256=checksum,byte_size=len(data),mime_type=MIME[name],storage_uri=uri))
    if chunks.chunks:
        repository.append_derived(chunks.manifest())
    publication = OutputPublication(revision=revision,files=stored)
    outputs = OutputRepository(repository._connect,repository._schema)
    inserted = outputs.publish_outputs(publication)
    return output,publication,inserted
