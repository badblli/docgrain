"""Local immutable KnowledgePack record artifacts; atomic publication after checksums.

This D5 adapter is separate from document outputs and never changes their bytes.
No read performs projection. Production shared/object storage is a later adapter.
"""

import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from docgrain_records.export import MODES, SCHEMA_VERSION, encode, export_bundle
from docgrain_records.merge_models import MergeRevision
from docgrain_records.review import SkipAnswer, answer_revision, questions, summary
from docgrain_records.runtime import revision_runtime


class PackMissing(LookupError):
    pass


class PackUnpublished(LookupError):
    pass


class QuestionStale(RuntimeError):
    pass


class AnswerInvalid(ValueError):
    pass


class RecordsRepository:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, workspace, revision=None):
        path = self.root / sha256(workspace.encode()).hexdigest()
        return path if revision is None else path / sha256(revision.encode()).hexdigest()

    def stage(self, revision: MergeRevision):
        """Immutable source preparation shared by offline and review publication."""
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
        with self._workspace_lock(revision.workspace_id):
            self._publish(revision)

    def _publish(self, revision: MergeRevision):
        self.stage(revision)
        path = self._path(revision.workspace_id, revision.id)
        published = path / "published"
        if published.exists():
            return  # Never regenerate an old publication.
        files = {mode: export_bundle(revision, mode) for mode in MODES}
        runtime = revision_runtime(revision)
        manifest = {"schema_version": SCHEMA_VERSION, "workspace_id": revision.workspace_id,
                    "revision_id": revision.id, "collections": list(runtime.collections.values()),
                    "published_at": datetime.now(UTC).isoformat(),
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
                    published.append((manifest.get("published_at") or datetime.fromtimestamp(
                        manifest_path.stat().st_mtime, UTC).isoformat(), manifest["revision_id"]))
            except (OSError, ValueError, KeyError):
                continue
        published.sort(key=lambda x: x[0], reverse=True)
        return [rev for _, rev in published]

    @contextmanager
    def _workspace_lock(self, workspace):
        """OS lock shared by API instances and offline publishers, released on process exit."""
        path = self._path(workspace)
        path.mkdir(parents=True, exist_ok=True)
        with (path / "review.lock").open("a+b") as lock:
            if os.name == "nt":
                import msvcrt

                if lock.tell() == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                except OSError as exc:
                    raise QuestionStale("workspace is busy; reload questions") from exc
                try:
                    yield
                finally:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _source(self, workspace, revision=None):
        if revision is None:
            revisions = self.list_revisions(workspace)
            if not revisions:
                raise PackMissing("workspace has no published revision")
            revision = revisions[0]
        self.manifest(workspace, revision)
        return MergeRevision.model_validate_json(
            (self._path(workspace, revision) / "source.json").read_bytes())

    def _review_state(self, workspace):
        path = self._path(workspace) / "review.json"
        return json.loads(path.read_bytes()) if path.exists() else {"issued": {}, "skipped": {}}

    def _save_review_state(self, workspace, state):
        path = self._path(workspace)
        descriptor, name = tempfile.mkstemp(dir=path)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(encode(state))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path / "review.json")
        finally:
            temporary.unlink(missing_ok=True)

    def workspace_summary(self, workspace, revision=None):
        with self._workspace_lock(workspace):
            source = self._source(workspace, revision)
            timestamp = (self._path(workspace, source.id) / "published" / "manifest.json").stat()
            return summary(source, datetime.fromtimestamp(timestamp.st_mtime, UTC).isoformat())

    def list_questions(self, workspace, revision=None, limit=20, offset=0):
        with self._workspace_lock(workspace):
            source = self._source(workspace, revision)
            state = self._review_state(workspace)
            items = questions(source)
            skipped = state["skipped"].get(source.id, [])
            ranks = {key: rank for rank, key in enumerate(skipped)}
            items.sort(key=lambda q: (q["kind"] == "needs_review", q["id"] in ranks,
                                      ranks.get(q["id"], -1)))
            page = items[offset:offset + limit]
            # Remember the revision served with each stable ID for the body-only write contract.
            for item in page:
                state["issued"][item["id"]] = source.id
            self._save_review_state(workspace, state)
            return {"total": len(items), "items": page}

    def answer_question(self, workspace, question_id, answer, revision=None):
        with self._workspace_lock(workspace):
            newest = self._source(workspace)
            state = self._review_state(workspace)
            expected = revision or state["issued"].get(question_id)
            if expected is None:
                raise PackMissing("question unknown; list questions first")
            if expected != newest.id:
                raise QuestionStale("question revision is no longer newest; reload questions")
            pending = questions(newest)
            if not any(q["id"] == question_id for q in pending):
                raise PackMissing("question unknown")
            if isinstance(answer, SkipAnswer):
                skipped = state["skipped"].setdefault(newest.id, [])
                skipped[:] = [key for key in skipped if key != question_id] + [question_id]
                self._save_review_state(workspace, state)
                return {"revision_id": newest.id, "remaining": len(pending)}
            try:
                updated = answer_revision(newest, question_id, answer)
            except ValueError as exc:
                raise AnswerInvalid("answer does not match the question field") from exc
            self._publish(updated)
            # Preserve skipped question positions within the same lineage after an answer.
            state["skipped"][updated.id] = state["skipped"].get(newest.id, [])
            self._save_review_state(workspace, state)
            return {"revision_id": updated.id, "remaining": len(questions(updated))}

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
