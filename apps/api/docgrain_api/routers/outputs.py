"""Stored pre-embedding outputs and verified portable bundle; no online derivation."""

from hashlib import sha256
from io import BytesIO
from urllib.parse import parse_qs, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

from docgrain_domain.canonical.ai_output import MIME, AIOutput
from fastapi import APIRouter, HTTPException, Response
from minio.error import S3Error

from ..output_repository import OutputRepository
from ..settings import get_settings
from ..storage import storage_client
from .knowledge import _store, get_revision

router = APIRouter(prefix="/v1/knowledge/revisions",tags=["knowledge"])


def _outputs(revision_id):
    get_revision(revision_id)  # stored revision and document/workspace gate, including demo mode
    store = _store()
    publication = OutputRepository(store._connect,store._schema).get_outputs(revision_id)
    if publication is None or publication.revision.processing_revision_id != revision_id:
        raise HTTPException(404,"AI output not published for this revision")
    return publication


def _bytes(uri, checksum, size, prefix=None):
    parsed = urlparse(uri)
    versions = parse_qs(parsed.query).get("versionId",[])
    settings = get_settings()
    key = parsed.path.lstrip("/")
    if (parsed.scheme != "s3" or parsed.netloc != settings.s3_bucket or len(versions)!=1
            or versions[0] == "null" or (prefix and not key.startswith(prefix))):
        raise HTTPException(404,"output object outside revision scope")
    try:
        response = storage_client().get_object(settings.s3_bucket,key,version_id=versions[0])
    except S3Error as error:
        if error.code in {"NoSuchKey","NoSuchVersion","NoSuchBucket"}:
            raise HTTPException(404,"published output object unavailable") from error
        raise
    try:
        data = response.read()
    finally:
        response.close()
        response.release_conn()
    if len(data) != size or sha256(data).hexdigest() != checksum:
        raise HTTPException(503,"output checksum verification failed")
    return data


def _file_bytes(publication,name):
    item = next((f for f in publication.files if f.name == name),None)
    if item is None or name not in MIME:
        raise HTTPException(404,"output file not found")
    revision = publication.revision
    prefix = f"knowledge/{revision.document_id}/{revision.processing_revision_id}/{revision.id}/"
    parsed = urlparse(item.storage_uri)
    if parsed.path.lstrip("/") != prefix+name:
        raise HTTPException(404,"output file outside publication scope")
    return _bytes(item.storage_uri,item.content_sha256,item.byte_size,prefix)


@router.get("/{revision_id}/outputs")
def get_outputs(revision_id: str):
    publication = _outputs(revision_id)
    data = AIOutput.model_validate_json(_file_bytes(publication,"ai.json"))
    return {"publication":publication,"output":data}


@router.get("/{revision_id}/outputs/{filename}")
def get_output_file(revision_id: str, filename: str):
    if filename not in MIME:
        raise HTTPException(404,"output file not found")
    publication = _outputs(revision_id)
    return Response(_file_bytes(publication,filename),media_type=MIME[filename],
        headers={"Content-Disposition":f'attachment; filename="{filename}"',"Cache-Control":"private, max-age=31536000, immutable"})


@router.get("/{revision_id}/package")
def get_package(revision_id: str):
    publication = _outputs(revision_id)
    published = {item.name for item in publication.files}
    files = {name:_file_bytes(publication,name) for name in MIME if name in published}
    output = AIOutput.model_validate_json(files["ai.json"])
    # Asset refs come from the authoritative stored revision, not arbitrary output URLs.
    snapshot = get_revision(revision_id)
    refs = {a.id:a for a in snapshot.artifacts}
    for asset in output.assets:
        authoritative = refs.get(asset.artifact.id)
        if authoritative != asset.artifact or not asset.file.startswith("assets/") or ".." in asset.file:
            raise HTTPException(503,"output asset differs from canonical revision")
        files[asset.file] = _bytes(authoritative.storage_uri,authoritative.content_sha256,authoritative.byte_size)
    archive = BytesIO()
    with ZipFile(archive,"w",compression=ZIP_DEFLATED) as bundle:
        for name,data in files.items():
            bundle.writestr(name,data)
    return Response(archive.getvalue(),media_type="application/zip",
                    headers={"Content-Disposition":f'attachment; filename="docgrain-{revision_id}.zip"'})
