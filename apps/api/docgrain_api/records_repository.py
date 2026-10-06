"""Local immutable KnowledgePack record artifacts; atomic publication after checksums.

This D5 adapter is separate from document outputs and never changes their bytes.
No read performs projection. Production shared/object storage is a later adapter.
"""

import json
import os
import re
import shutil
import tempfile
from hashlib import sha256
from pathlib import Path

from docgrain_records.export import MODES, SCHEMA_VERSION, encode, export_bundle
from docgrain_records.merge_models import MergeRevision
from docgrain_records.runtime import revision_runtime


class PackMissing(LookupError):
    pass


class PackUnpublished(LookupError):
    pass


class RecordsRepository:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, workspace, revision=None):
        path = self.root / sha256(workspace.encode()).hexdigest()
        return path if revision is None else path / sha256(revision.encode()).hexdigest()

    def stage(self, revision: MergeRevision):
        """Explicit offline preparation; no HTTP write surface."""
        path = self._path(revision.workspace_id, revision.id)
        body = revision.model_dump_json(round_trip=True).encode()
        path.mkdir(parents=True, exist_ok=True)
        source = path / "source.json"
        descriptor, name = tempfile.mkstemp(dir=path)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, source)  # Atomic create-if-absent, never overwrite.
            except FileExistsError:
                if source.read_bytes() != body:
                    raise ValueError("revision already exists with different content") from None
        finally:
            temporary.unlink()

    def publish(self, revision: MergeRevision):
        self.stage(revision)
        path = self._path(revision.workspace_id, revision.id)
        published = path / "published"
        if published.exists():
            return  # Never regenerate an old publication.
        files = {mode: export_bundle(revision, mode) for mode in MODES}
        runtime = revision_runtime(revision)
        manifest = {"schema_version": SCHEMA_VERSION, "workspace_id": revision.workspace_id,
                    "revision_id": revision.id, "collections": list(runtime.collections.values()),
                    "modes": {mode: {"files": {name: sha256(body).hexdigest()
                                               for name, body in artifacts.items()}}
                              for mode, artifacts in files.items()}}
        if runtime.schema:
            manifest["workspace_schema_version"] = runtime.schema["version"]
        temporary = Path(tempfile.mkdtemp(dir=path))
        try:
            for mode, artifacts in files.items():
                destination = temporary / mode
                destination.mkdir()
                for name, body in artifacts.items():
                    with (destination / name).open("xb") as output:
                        output.write(body)
                        output.flush()
                        os.fsync(output.fileno())
            with (temporary / "manifest.json").open("xb") as output:
                output.write(encode(manifest))
                output.flush()
                os.fsync(output.fileno())
            try:
                temporary.rename(published)
            except OSError:
                if not published.exists():
                    raise
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def manifest(self, workspace, revision):
        path = self._path(workspace, revision)
        if not path.is_dir():
            raise PackMissing("workspace or revision unknown")
        publication = path / "published" / "manifest.json"
        if not publication.is_file():
            raise PackUnpublished("revision not published")
        manifest = json.loads(publication.read_bytes())
        if (manifest["workspace_id"], manifest["revision_id"]) != (workspace, revision):
            raise PackMissing("publication outside workspace/revision")
        source = MergeRevision.model_validate_json((path / "source.json").read_bytes())
        if (source.workspace_id, source.id) != (workspace, revision):
            raise ValueError("record source outside workspace/revision")
        runtime = revision_runtime(source)
        if (manifest["schema_version"] != SCHEMA_VERSION or
                manifest["collections"] != list(runtime.collections.values()) or
                manifest.get("workspace_schema_version") != (
                    runtime.schema["version"] if runtime.schema else None) or
                set(manifest["modes"]) != set(MODES) or
                any(not re.fullmatch(
                    r"(?:" + "|".join(runtime.collections.values()) +
                    r")(?:\.[a-z]{2,3}(?:-[a-z0-9]{2,8})*)?\.(?:json|context\.md)", name)
                    for mode in MODES for name in manifest["modes"][mode]["files"])):
            raise ValueError("invalid record artifact manifest")
        return manifest

    def list_revisions(self, workspace):
        path = self._path(workspace)
        if not path.is_dir():
            return []
        published = []
        for d in path.iterdir():
            if not d.is_dir():
                continue
            manifest_path = d / "published" / "manifest.json"
            try:
                manifest = json.loads(manifest_path.read_bytes())
                if manifest["workspace_id"] == workspace:
                    published.append((manifest_path.stat().st_mtime, manifest["revision_id"]))
            except (OSError, ValueError, KeyError):
                continue
        published.sort(key=lambda x: x[0], reverse=True)
        return [rev for _, rev in published]

    def read(self, workspace, revision, collection, lang=None, compact=False,
             mode="preview"):
        if mode not in MODES:
            raise ValueError("unknown publication mode")
        manifest = self.manifest(workspace, revision)
        if collection not in manifest["collections"]:
            raise PackMissing("collection unknown")
        extension = "context.md" if compact else "json"
        name = f"{collection}.{lang}.{extension}" if lang and lang != "en" else ""
        checksums = manifest["modes"][mode]["files"]
        if name not in checksums:
            name = f"{collection}.{extension}"
        body = (self._path(workspace, revision) / "published" / mode / name).read_bytes()
        if sha256(body).hexdigest() != checksums[name]:
            raise ValueError("published artifact checksum mismatch")
        return body
