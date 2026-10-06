"""Read-only, explicitly pinned workspace KnowledgePack access."""

import json
from hashlib import sha256

from docgrain_records.export import MODES
from fastapi import APIRouter, HTTPException, Request, Response

from ..records_repository import PackMissing, PackUnpublished, RecordsRepository
from ..settings import get_settings

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/revisions/{revision_id}",
                   tags=["records"])
workspace_router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["records"])

@workspace_router.get("/revisions")
def list_revisions(workspace_id: str):
    return repository().list_revisions(workspace_id)


def repository():
    root = get_settings().records_publication_root
    if not root:
        raise HTTPException(404, "record publications unavailable")
    return RecordsRepository(root)


def _response(request, workspace, revision, collection=None, lang=None, compact=False,
              record_id=None, mode="preview"):
    if mode not in MODES:
        raise HTTPException(422, "unknown publication mode")
    try:
        store = repository()
        manifest = store.manifest(workspace, revision)
        if collection is None:
            body = json.dumps({key: manifest[key] for key in (
                "schema_version", "workspace_id", "revision_id", "collections")}
                | {"mode": mode},
                sort_keys=True).encode()
        else:
            body = store.read(workspace, revision, collection, lang, compact, mode)
            if record_id is not None:
                row = next((r for r in json.loads(body) if r["id"] == record_id), None)
                if row is None:
                    raise PackMissing("record unknown")
                body = json.dumps(row, ensure_ascii=False, sort_keys=True).encode()
    except PackUnpublished as exc:
        raise HTTPException(409, str(exc)) from exc
    except PackMissing as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise HTTPException(503, "published artifact unavailable or invalid") from exc
    etag = '"' + sha256(workspace.encode() + b"\0" + revision.encode() + b"\0" +
                        mode.encode() + b"\0" + body).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=31536000, immutable",
               "X-Docgrain-Workspace": workspace, "X-Docgrain-Revision": revision,
               "X-Docgrain-Schema-Version": manifest["schema_version"],
               "X-Docgrain-Publication-Mode": mode}
    matches = [tag.strip().removeprefix("W/") for tag in
               request.headers.get("if-none-match", "").split(",")]
    if etag in matches or "*" in matches:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="text/markdown" if compact else "application/json",
                    headers=headers)


@router.get("/collections")
def list_collections(request: Request, workspace_id: str, revision_id: str,
                     mode: str = "preview"):
    return _response(request, workspace_id, revision_id, mode=mode)


@router.get("/collections/{collection}")
def get_collection(request: Request, workspace_id: str, revision_id: str,
                   collection: str, lang: str | None = None, mode: str = "preview"):
    return _response(request, workspace_id, revision_id, collection, lang, mode=mode)


@router.get("/collections/{collection}/context")
def get_context(request: Request, workspace_id: str, revision_id: str,
                collection: str, lang: str | None = None, mode: str = "preview"):
    return _response(request, workspace_id, revision_id, collection, lang, compact=True,
                     mode=mode)


@router.get("/collections/{collection}/records/{record_id}")
def get_record(request: Request, workspace_id: str, revision_id: str,
               collection: str, record_id: str, lang: str | None = None,
               mode: str = "preview"):
    return _response(request, workspace_id, revision_id, collection, lang,
                     record_id=record_id, mode=mode)
