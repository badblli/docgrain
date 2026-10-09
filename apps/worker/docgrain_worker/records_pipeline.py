"""Bounded U1 orchestration of the existing records CLI functions, in process.

The supervisor can terminate a hung stage; GET only fences stale jobs, never replays.
All source bodies and model proposals stay under the private runtime directory.
"""

import logging
import multiprocessing
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event, Thread

import httpx
from docgrain_api import records_jobs as lifecycle
from docgrain_api import records_jobs_repository as jobs
from docgrain_api.settings import get_settings
from docgrain_api.workspace_settings import ModelSettingsError, resolve_workspace_model
from docgrain_records.discovery import (
    DiscoveryClient,
    discover,
    source_pins,
    verify_examples,
)
from docgrain_records.discovery_cli import load_workspace_documents
from docgrain_records.discovery_models import DiscoveryResponse
from docgrain_records.discovery_store import (
    accept_schema,
    source_directory,
    write_proposal,
)
from docgrain_records.export import load_revision
from docgrain_records.extractor import _blocks, extract, extraction_plan
from docgrain_records.match import accept_strong_matches, load_records, propose_matches
from docgrain_records.match_merge import merge_matches, write_json
from docgrain_records.model import ChatClient
from docgrain_records.models import ExtractionUsage
from docgrain_records.runtime import load_runtime

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(lifecycle.ERRORS[code])


class GuardTransport(httpx.BaseTransport):
    """Recheck opt-in before EVERY physical request, including retry/fallback requests."""

    def __init__(self, guard, transport=None):
        self.guard = guard
        self.transport = transport or httpx.HTTPTransport()

    def handle_request(self, request):
        self.guard()
        return self.transport.handle_request(request)

    def close(self):
        self.transport.close()


def model_client(kind, resolved, guard, transport=None):
    chat = kind(resolved.base_url, resolved.model, resolved.api_key or "local-profile",
                timeout=180, retries=3, transport=GuardTransport(guard, transport))
    # Existing ChatClient requires a nonempty key. An explicitly keyless server profile
    # still uses that same client, with no invented credential sent to the endpoint.
    if not resolved.api_key:
        del chat.client.headers["Authorization"]
    return chat


class CheckedDiscovery:
    """Observe full definitions before discovery's supported-field filtering."""

    def __init__(self, chat, documents, root):
        self.chat = chat
        self.blocks = {d.source.document_id: _blocks(d.context) for d in documents}
        self.root = root
        self.needs_review = False

    def complete(self, messages, **kwargs):
        raw = self.chat.complete(messages, **kwargs)
        response = DiscoveryResponse.model_validate_json(raw)
        for collection in response.collections:
            rejected = []
            verified = verify_examples(collection, self.blocks, rejected)
            supported = {value.key for example in verified for value in example.values}
            if rejected or supported != {field.key for field in collection.fields}:
                self.needs_review = True
                # Keep the complete proposal for the lead, never silently prune it.
                write_json(self.root / "schema.review.json", response.model_dump(mode="json"))
        return raw


class Pipeline:
    def __init__(self, job, transport=None, document_loader=None):
        self.job = job
        self.workspace = job["workspace_id"]
        self.job_id = job["job_id"]
        self.store = lifecycle.pack_store()
        self.root = (self.store._path(self.workspace) / "runtime" /
                     sha256(self.job_id.encode()).hexdigest())
        self.transport = transport
        self.document_loader = document_loader or load_workspace_documents
        self.documents = []
        self.schema = None
        self.runtime = None
        self.results = None
        self.matches = None
        self.revision = None
        self.schema_review = False
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)

    def guard(self):
        current = jobs.get(self.workspace, self.job_id)
        if not current or current["status"] != "running":
            raise PipelineError("worker_stale")
        if code := lifecycle.expired(current):
            raise PipelineError(code)
        if get_settings().use_fixtures:
            raise PipelineError("guard")
        return resolve_workspace_model(self.workspace, self.job["settings_version"])

    def sources_unchanged(self):
        if lifecycle.source_snapshot(self.workspace) != self.job["sources"]:
            raise PipelineError("source_changed")

    def publication_unchanged(self):
        if (lifecycle.head(self.store, self.workspace) != self.job["publication_head"]
                or lifecycle.has_accepted(self.store, self.workspace)):
            raise PipelineError("publication_changed")

    def metadata(self, **values):
        def mutate(job):
            job["metadata"].update(values)
        if not jobs.change(self.workspace, self.job_id, mutate, {"running"}):
            raise PipelineError("worker_stale")

    def discover(self):
        resolved = self.guard()
        self.sources_unchanged()
        self.publication_unchanged()
        # Failed documents are not pinned at start (records_jobs.source_snapshot skips them); load only pins.
        pinned = {pin["document_id"] for pin in self.job["sources"]}
        api_url = os.environ.get("DOCGRAIN_INTERNAL_API_URL", "http://api:8000")
        try:
            self.documents = self.document_loader(api_url, self.workspace, document_ids=pinned)
        except TypeError:  # older/fake loaders without the filter argument
            self.documents = self.document_loader(api_url, self.workspace)
        self.documents = [doc for doc in self.documents if doc.source.document_id in pinned]
        actual = [{key: getattr(doc.source, key) for key in
                   ("document_id", "source_version_id", "knowledge_revision_id", "content_sha256")}
                  for doc in sorted(self.documents, key=lambda d: d.source.document_id)]
        expected = [{k: v for k, v in pin.items() if k != "document_version_id"}
                    for pin in self.job["sources"]]
        if actual != expected:
            raise PipelineError("source_changed")
        pins = source_pins(self.documents, self.workspace)
        self.metadata(normalized_sources=[pin.model_dump(mode="json") for pin in pins])
        for doc in self.documents:
            path = self.root / "records" / sha256(doc.source.document_id.encode()).hexdigest()
            write_json(path / "source.json", doc.source.model_dump(mode="json"))
            (path / "context.md").write_bytes(doc.context.encode("utf-8"))
        chat = model_client(DiscoveryClient, resolved, self.guard, self.transport)
        checked = CheckedDiscovery(chat, self.documents, self.root)
        try:
            self.schema = discover(self.documents, self.workspace, checked)
            self.schema_review = checked.needs_review
        finally:
            chat.close()
        write_proposal(self.root / "schema", self.schema, self.documents)
        for pin in self.schema.sources:
            doc = next(d for d in self.documents if d.source.document_id == pin.document_id)
            write_json(source_directory(self.root / "schema", pin) / "source.json",
                       doc.source.model_dump(mode="json"))

    def accept_schema(self):
        schema = self.schema
        if not schema.collections:
            raise PipelineError("schema_review" if self.schema_review or schema.rejected else "empty")
        blocks = {doc.source.document_id: _blocks(doc.context) for doc in self.documents}
        if self.schema_review or schema.rejected:
            raise PipelineError("schema_review")
        for collection in schema.collections:
            rejected = []
            examples = verify_examples(collection, blocks, rejected)
            if (collection.review_state != "proposed" or rejected
                    or any(field.alternatives or field.review_state != "proposed"
                           for field in collection.fields)
                    or {v.key for e in examples for v in e.values} != {f.key for f in collection.fields}):
                raise PipelineError("schema_review")
        # Nothing is removed. The rule accepts definitions only, never record values.
        for collection in schema.collections:
            collection.review_state = "accepted"
            for field in collection.fields:
                field.review_state = "accepted"
        write_json(self.root / "schema" / "schema.proposed.json", schema.model_dump(mode="json"))
        try:
            self.schema = accept_schema(self.root / "schema" / "schema.proposed.json", self.root / "schema")
        except ValueError:
            raise PipelineError("schema_review") from None
        self.metadata(schema_acceptance={
            "reviewer": "rule:u1-verified-schema",
            "reason": "Her alanın tipi ve sabit kaynak alıntısı doğrulandı; alternatif tanım yok.",
            "version": self.schema.version,
            "collections": [c.key for c in self.schema.collections],
        })
        self.runtime = load_runtime(self.root / "schema" / f"schema.v{self.schema.version}.json")

    def extract(self):
        chat = model_client(ChatClient, self.guard(), self.guard, self.transport)
        plans = {}
        try:
            for doc in self.documents:
                self.guard()
                usage = ExtractionUsage()
                plans[doc.source.document_id] = len(extraction_plan(doc.context, runtime=self.runtime))
                result = extract(doc.context, doc.source.document_id, doc.source.lang, chat,
                                 concurrency=1, usage=usage, runtime=self.runtime)
                path = self.root / "records" / sha256(doc.source.document_id.encode()).hexdigest()
                doc.source.usage = usage
                write_json(path / "source.json", doc.source.model_dump(mode="json"))
                write_json(path / "records.json", result.model_dump(mode="json", exclude_none=True))
                if result.failures or result.rejected:
                    raise PipelineError("incomplete")
        finally:
            chat.close()
        self.metadata(extraction_plans=plans)
        self.results = load_records(self.root / "records", runtime=self.runtime)
        if not any(result.records for result in self.results):
            raise PipelineError("empty")

    def match(self):
        # No PairClient/model judge. This rule accepts identities only.
        self.matches = accept_strong_matches(self.results, propose_matches(self.results))
        write_json(self.root / "match" / "match_proposals.json", self.matches.model_dump(mode="json"))

    def merge(self):
        merge_matches(self.root / "records", self.results, self.matches, self.root / "merged",
                      self.workspace, "u1_" + self.job_id, "strong")
        self.revision = load_revision((self.root / "merged" / "merge_revision.json").read_bytes())
        if not self.revision.records:
            raise PipelineError("empty")
        audit = []
        for record in self.revision.records:
            for key, field in record.fields.items():
                for candidate in field.candidates:
                    if candidate.review_state == "proposed":
                        candidate.review_state = "needs_review"
                        audit.append({"record_id": record.id, "field": key, "candidate_id": candidate.id,
                                      "state": "needs_review", "reviewer": "rule:u1-human-field-review",
                                      "reason": "Kimlik eşleşmesi alan onayı değildir; insan onayı gerekli."})
        self.metadata(field_review_audit=audit)
        write_json(self.root / "merged" / "merge_revision.json", self.revision.model_dump(mode="json"))

    def publish(self):
        def check():
            self.guard()
            self.sources_unchanged()
            self.publication_unchanged()
        def complete():
            manifest = self.store.manifest(self.workspace, self.revision.id, pending_job=self.job_id)
            for collection in manifest["collections"]:
                for mode in ("preview", "approved"):
                    self.store.read(self.workspace, self.revision.id, collection, mode=mode,
                                    pending_job=self.job_id)
            if not lifecycle.finish(self.workspace, self.job_id, revision_id=self.revision.id):
                raise PipelineError("worker_stale")
        # stage is immutable and invisible. publish repeats checks inside the common lock.
        self.store.stage(self.revision)
        self.store.publish(self.revision, check=check, complete=complete, job_id=self.job_id)

    def run(self):
        for stage in lifecycle.STAGES:
            self.guard()
            stamp = lifecycle.now()
            def begin(job, stage=stage, stamp=stamp):
                job.update(stage=stage, message=lifecycle.LABELS[stage], heartbeat_at=stamp,
                           stage_deadline=(datetime.now(UTC) + timedelta(
                               seconds=lifecycle.STAGE_TIMEOUTS[stage])).isoformat())
                job["stages"][stage].update(status="running", started_at=stamp)
            if not jobs.change(self.workspace, self.job_id, begin, {"running"}):
                raise PipelineError("worker_stale")
            getattr(self, stage)()
            if stage == "publish":
                return  # Publication read verification and terminal write share its lock.
            self.guard()
            def complete(job, stage=stage):
                job["stages"][stage].update(status="done", finished_at=lifecycle.now())
                job["completed_stages"] += 1
            if not jobs.change(self.workspace, self.job_id, complete, {"running"}):
                raise PipelineError("worker_stale")


def process_job(job_id, transport=None, document_loader=None):
    job = jobs.locate(job_id)
    if not job:
        return
    workspace = job["workspace_id"]
    stop = Event()

    def heartbeat():
        while not stop.wait(10):
            try:
                if not jobs.change(workspace, job_id,
                                   lambda j: j.update(heartbeat_at=lifecycle.now()), {"running"}):
                    return
            except Exception:  # noqa: BLE001 - stale detection handles any heartbeat storage failure.
                return  # Supervisor/GET detects the missing heartbeat; no automatic replay.

    with lifecycle.pack_store()._workspace_lock(workspace):
        lifecycle.reap_locked(workspace)
        job = jobs.change(workspace, job_id, lambda j: j.update(
            status="running", started_at=lifecycle.now(), heartbeat_at=lifecycle.now()), {"queued"})
    if not job:
        return
    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        Pipeline(job, transport, document_loader).run()
    except Exception as exc:  # noqa: BLE001 - persist a fixed terminal error for any failed stage.
        code = (exc.code if isinstance(exc, (PipelineError, lifecycle.JobConflict)) else
                "guard" if isinstance(exc, ModelSettingsError) else "step_failed")
        # Never log exception text: providers may include credentials or sources. The exception type
        # and code locations (file:line:function, no locals or messages) are safe and make failures fixable.
        logger.error("record job stopped (%s) %s at %s", code, type(exc).__name__, _safe_frames(exc))
        with lifecycle.pack_store()._workspace_lock(workspace):
            lifecycle.finish(workspace, job_id, code)
    finally:
        stop.set()
        thread.join(timeout=1)


def _safe_frames(exc, limit=6):
    """Innermost code locations of an exception chain, without messages or local values."""
    import traceback

    frames = traceback.extract_tb(exc.__traceback__)[-limit:]
    return " <- ".join(f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}" for f in reversed(frames))


def _run_child(job_id):
    try:
        process_job(job_id)
    except Exception:  # noqa: BLE001 - no raw subprocess traceback from storage/credential errors.
        logger.error("record worker stopped (worker_stale)")


def supervise(job_id):
    """A separate process bounds even hung disk/model operations and releases OS locks."""
    process = multiprocessing.get_context("spawn").Process(target=_run_child, args=(job_id,))
    process.start()
    job = jobs.locate(job_id)
    try:
        while process.is_alive():
            process.join(timeout=1)
            current = jobs.locate(job_id)
            if current and (current["status"] not in jobs.ACTIVE or lifecycle.expired(current)):
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=5)
                break
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        if job:
            with lifecycle.pack_store()._workspace_lock(job["workspace_id"]):
                current = jobs.locate(job_id)
                if current and current["status"] in jobs.ACTIVE:
                    lifecycle.finish(job["workspace_id"], job_id,
                                     lifecycle.expired(current) or "worker_stale")
