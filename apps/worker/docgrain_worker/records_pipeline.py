"""Bounded U1 orchestration of the existing records CLI functions, in process.

The supervisor can terminate a hung stage; GET only fences stale jobs, never replays.
All source bodies and model proposals stay under the private runtime directory.
"""

import json
import logging
import multiprocessing
import os
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event, Lock, Thread
from urllib.parse import parse_qs, quote, urlparse

import httpx
from docgrain_api import records_jobs as lifecycle
from docgrain_api import records_jobs_repository as jobs
from docgrain_api.settings import get_settings
from docgrain_api.workspace_settings import (
    ModelSettingsError,
    get_workspace_model,
    resolve_workspace_model,
)
from docgrain_records.auto_accept import apply_review_rules
from docgrain_records.carry_forward import carry_forward, unchanged
from docgrain_records.collection_merge import remembered
from docgrain_records.discovery import (
    FIELD_SYNONYMS,
    DiscoveryClient,
    discover,
    source_pins,
    update_coverage,
    verify_examples,
)
from docgrain_records.discovery_cli import load_workspace_documents
from docgrain_records.discovery_models import (
    DiscoveryResponse,
    Example,
    WorkspaceSchema,
)
from docgrain_records.discovery_store import (
    accept_schema,
    source_directory,
    write_proposal,
)
from docgrain_records.export import load_revision
from docgrain_records.extractor import (
    ExtractionRun,
    _blocks,
    extract,  # KULLANILMIYOR (karar 18, WP110): yalnız _extract_before_wp110 kullanıyor.
    extraction_plan,  # KULLANILMIYOR (karar 18, WP110): yalnız _extract_before_wp110 kullanıyor.
)
from docgrain_records.match import accept_strong_matches, load_records, propose_matches
from docgrain_records.match_merge import merge_matches, write_json
from docgrain_records.merge_models import MergeRevision
from docgrain_records.model import ChatClient
from docgrain_records.models import ExtractionUsage
from docgrain_records.runtime import RuntimeRecords, load_runtime
from docgrain_records.structure_records import build_structure_plan, reduced_context
from docgrain_records.verify import _coalesce_document_records, verify_response

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


def model_client(kind, resolved, guard, transport=None, on_usage=None):
    chat = kind(resolved.base_url, resolved.model, resolved.api_key or "local-profile",
                timeout=180, retries=3, transport=GuardTransport(guard, transport),
                reasoning_effort=getattr(resolved, "reasoning_effort", None),
                max_tokens=getattr(resolved, "max_tokens", None),
                on_usage=on_usage)
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
        # WP110: (collection, field) definitions that could not be verified, in model order.
        self.unverified = []

    def complete(self, messages, **kwargs):
        raw = self.chat.complete(messages, **kwargs)
        response = DiscoveryResponse.model_validate_json(raw)
        for collection in response.collections:
            rejected = []
            verified = verify_examples(collection, self.blocks, rejected)
            supported = {value.key for example in verified for value in example.values}
            if rejected or supported != {field.key for field in collection.fields}:
                self.needs_review = True
                failed = {item.field for item in rejected}
                self.unverified.extend((collection, field) for field in collection.fields
                                       if field.key in failed or field.key not in supported)
                # Keep the complete proposal for the lead, never silently prune it.
                write_json(self.root / "schema.review.json", response.model_dump(mode="json"))
        return raw


# Same order as discovery_store.accept_schema, which picks a collection's identity from these.
IDENTITY_FIELDS = ("name", "title", "question", "term", "label")


def _label(labels, fallback):
    """Plain name for the job report: Turkish, else English, else the key."""
    values = {label.lang: label.value for label in labels}
    return values.get("tr") or values.get("en") or fallback


def _review_item(collection, field, reason):
    """A definition set aside for review; no source text, only keys and schema labels."""
    name = _label(collection.label_i18n, collection.key)
    return {"collection": collection.key, "field": field.key if field else None, "reason": reason,
            "label": f"{name}: {_label(field.label_i18n, field.key)}" if field else name}


def review_counts(audit):
    """Rule outcomes for the job report: reviewer -> number of field values."""
    return dict(sorted(Counter(item["reviewer"] for item in audit).items()))


def _s3_object(uri, checksum):
    """A pinned, versioned artifact from the workspace bucket, checked against its SHA-256."""
    from docgrain_api.storage import storage_client

    parsed = urlparse(uri)
    versions = parse_qs(parsed.query).get("versionId", [])
    if parsed.scheme != "s3" or parsed.netloc != get_settings().s3_bucket or len(versions) != 1:
        return None
    response = storage_client().get_object(parsed.netloc, parsed.path.lstrip("/"),
                                           version_id=versions[0])
    try:
        data = response.read()
    finally:
        response.close()
        response.release_conn()
    return data if sha256(data).hexdigest() == checksum else None


def load_docling_documents(api_url, workspace_id, pins):
    """WP119: the stored DoclingDocument JSON of each pinned version, or None (read-only).

    Same sources as benchmarks/structure_coverage.py: the canonical snapshot's inline
    ``metadata.docling_document``, else its ``docling-document`` artifact from object storage
    (checksum verified), else the PDF ``document.json`` artifact. A snapshot of another revision
    than the pin is not used. Failures leave the document to the model fallback.
    """
    result = {}
    with httpx.Client(base_url=api_url.rstrip("/"), timeout=60) as api:
        for pin in pins:
            document = pin["document_id"]
            result[document] = None
            try:
                response = api.get(f"/v1/documents/{quote(document, safe='')}/knowledge")
                response.raise_for_status()
                snapshot = response.json().get("snapshot") or {}
                if (snapshot.get("knowledge_revision") or {}).get("id") != pin["knowledge_revision_id"]:
                    continue
                inline = (snapshot.get("metadata") or {}).get("docling_document")
                if isinstance(inline, dict):
                    result[document] = inline
                    continue
                artifact = next((a for a in snapshot.get("artifacts") or []
                                 if a.get("role") == "docling-document"), None)
                if artifact:
                    data = _s3_object(artifact.get("storage_uri", ""), artifact.get("content_sha256"))
                    if data is not None:
                        result[document] = json.loads(data)
                        continue
                version = pin.get("document_version_id")
                if version:
                    response = api.get(f"/v1/documents/{quote(document, safe='')}/versions/"
                                       f"{quote(version, safe='')}/artifacts/document.json")
                    if response.status_code == 200:
                        result[document] = response.json()
            except Exception:  # noqa: BLE001 - structure is optional; the model path stays available.
                logger.warning("docling structure unavailable for one document")
    return result


def _no_docling(*_args):
    """Callers that supply their own documents (tests, CLI) have no stored Docling JSON."""
    return {}


def combine_schemas(structure, model):
    """WP119: structure collections first; a model collection with the same key only adds fields."""
    if structure is None or model is None:
        return structure or model
    schema = structure.model_copy(deep=True)
    collections = {collection.key: collection for collection in schema.collections}
    for incoming in model.collections:
        target = collections.get(incoming.key)
        if target is None:
            collections[incoming.key] = incoming.model_copy(deep=True)
            continue
        known = {field.key for field in target.fields}
        added = [field for field in incoming.fields if field.key not in known]
        target.fields.extend(field.model_copy(deep=True) for field in added)
        keys = {field.key for field in added}
        for example in incoming.examples:
            values = [value for value in example.values if value.key in keys]
            if values:
                target.examples.append(Example(values=values))
        target.aliases = sorted(set(target.aliases) | set(incoming.aliases))
    schema.collections = [collections[key] for key in sorted(collections)]
    schema.rejected = list(model.rejected)
    return schema


class Pipeline:
    stages = lifecycle.STAGES
    labels = lifecycle.LABELS
    stage_timeouts = lifecycle.STAGE_TIMEOUTS

    def __init__(self, job, transport=None, document_loader=None, concurrency=None,
                 docling_loader=None):
        self.job = job
        self.workspace = job["workspace_id"]
        self.job_id = job["job_id"]
        self.store = lifecycle.pack_store()
        self.root = (self.store._path(self.workspace) / "runtime" /
                     sha256(self.job_id.encode()).hexdigest())
        self.transport = transport
        self.document_loader = document_loader or load_workspace_documents
        # WP119: a caller supplying documents without a Docling source gets no structure.
        self.docling_loader = docling_loader or (
            load_docling_documents if document_loader is None else _no_docling)
        self.model_enabled = job.get("model_enabled", True)
        self.plan = None
        self.fallback = []
        self.remembered_decisions = []
        self.structure_report = {}
        self.documents = []
        self.schema = None
        self.runtime = None
        self.results = None
        self.matches = None
        self.revision = None
        self.schema_review = False
        self.unverified = []
        self.measurements = {"stages": {}, "calls": []}
        self.measurement_lock = Lock()
        self.base = (self.store._source(self.workspace, job["publication_head"])
                     if job.get("publication_head") else None)
        self.reused = {}
        self.saved_discovery = None
        self.cached_schema = (WorkspaceSchema.model_validate(self.base.workspace_schema)
                              if self.base and self.base.workspace_schema else None)
        # WP113: parallel extraction calls (1-32); record and usage order stay in plan order.
        self.concurrency = concurrency or get_settings().records_extraction_concurrency
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)

    def guard(self):
        current = jobs.get(self.workspace, self.job_id)
        if not current or current["status"] != "running":
            raise PipelineError("worker_stale")
        if code := lifecycle.expired(current):
            raise PipelineError(code)
        if get_settings().use_fixtures:
            raise PipelineError("guard")
        if self.model_enabled:
            return resolve_workspace_model(self.workspace, self.job["settings_version"])
        # WP119: a structure-only job (model off) still stops when the settings change.
        if int(get_workspace_model(self.workspace)["settings_version"]) != self.job["settings_version"]:
            raise ModelSettingsError("Model ayarları değişti; işlemi yeniden başlatın.")
        return None

    def sources_unchanged(self):
        if lifecycle.source_snapshot(self.workspace) != self.job["sources"]:
            raise PipelineError("source_changed")

    def publication_unchanged(self):
        if lifecycle.head(self.store, self.workspace) != self.job["publication_head"]:
            raise PipelineError("publication_changed")

    # KULLANILMIYOR (karar 18, WP125): onaylı herhangi bir alan işi durduruyordu.
    # Dosyanın WP125 öncesi tam kopyası: unused/wp125/records_pipeline.py.
    def _publication_unchanged_before_wp125(self):
        if (lifecycle.head(self.store, self.workspace) != self.job["publication_head"]
                or lifecycle.has_accepted(self.store, self.workspace)):
            raise PipelineError("publication_changed")

    def _reuse_documents(self):
        """Find extraction artifacts through review/fill ancestry, only for head pins.

        A cache is private to its workspace and published ancestor job. Missing/old
        artifacts cause normal processing; an unrelated run can never supply results.
        """
        if self.base is None or self.cached_schema is None:
            return
        ancestor = self.base
        root = None
        while ancestor:
            job_id = self.store.manifest(self.workspace, ancestor.id).get("record_job_id")
            if job_id:
                candidate = self.store._path(self.workspace) / "runtime" / sha256(job_id.encode()).hexdigest()
                if (candidate / "records").is_dir():
                    root = candidate
                    break
            ancestor = self.store._source(self.workspace, ancestor.parent_id) if ancestor.parent_id else None
        if root is None:
            return
        manifest = (json.loads((root / "reuse.json").read_bytes())
                    if (root / "reuse.json").is_file() else {})
        plan = (json.loads((root / "structure" / "plan.json").read_bytes())
                if (root / "structure" / "plan.json").is_file() else {})
        previous = {p.document_id: p for p in self.base.documents}
        for doc in self.documents:
            key = doc.source.document_id
            if not unchanged(previous.get(key), doc.source):
                continue
            path = root / "records" / sha256(key.encode()).hexdigest() / "records.json"
            # Pre-WP125 jobs already stored these immutable per-document artifacts.
            source_path = path.with_name("source.json")
            cached_pin = manifest.get("documents", {}).get(key) or (
                json.loads(source_path.read_bytes()) if source_path.is_file() else None)
            if not cached_pin or any(cached_pin.get(k) != getattr(doc.source, k) for k in (
                    "content_sha256", "knowledge_revision_id")) or not path.is_file():
                continue
            result = json.loads(path.read_bytes())
            if result.get("failures"):
                continue  # Retry incomplete extraction rather than permanently caching gaps.
            # A document that needed the model while it was off is read once the model is on.
            pending = cached_pin.get("model_pending", key in plan.get("documents_needing_model", [])
                                     and not cached_pin.get("usage"))
            if pending and self.model_enabled:
                continue
            calls = cached_pin.get("model_calls", len((cached_pin.get("usage") or {}).get("calls", [])))
            self.reused[key] = (result, calls, pending)
        discovery = manifest.get("discovery")
        if discovery and set(discovery["documents"]) <= set(self.reused):
            self.saved_discovery = discovery

    def _accepted_update_schema(self):
        """Preserve accepted definitions (including user additions); pin current sources."""
        schema = combine_schemas(self.cached_schema, self.schema)
        schema.sources = source_pins(self.documents, self.workspace)
        self.schema = schema
        self.runtime = RuntimeRecords(schema)
        write_json(self.root / "schema" / f"schema.v{schema.version}.json", schema.model_dump(mode="json"))

    def metadata(self, **values):
        def mutate(job):
            job["metadata"].update(values)
        if not jobs.change(self.workspace, self.job_id, mutate, {"running"}):
            raise PipelineError("worker_stale")

    def account(self, stage):
        def record(values):
            with self.measurement_lock:
                self.measurements["calls"].append({"stage": stage, **values})
                self.metadata(speed=self.measurements)
        return record

    def _load_documents(self):
        """Load exactly the pinned documents and keep their pinned source/context for merge."""
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

    def _remembered(self):
        """WP119: "same list?" answers kept on the published head (inherited across runs)."""
        head = lifecycle.head(self.store, self.workspace)
        if not head:
            return {}, []
        try:
            revision = self.store._source(self.workspace, head)
        except Exception:  # noqa: BLE001 - an unreadable head only means nothing is remembered.
            return {}, []
        return remembered([revision]), list(revision.collection_merge_decisions)

    def structure(self):
        """WP119 (karar 21): collections and records from Docling structure; no model call."""
        self.guard()
        self.sources_unchanged()
        self.publication_unchanged()
        self._load_documents()
        self._reuse_documents()
        changed = [doc for doc in self.documents if doc.source.document_id not in self.reused]
        api_url = os.environ.get("DOCGRAIN_INTERNAL_API_URL", "http://api:8000")
        try:
            doclings = self.docling_loader(api_url, self.workspace, self.job["sources"])
        except Exception:  # noqa: BLE001 - without structure every document takes the model path.
            logger.warning("docling structure could not be loaded")
            doclings = {}
        decisions, self.remembered_decisions = self._remembered()
        # WP125: grouping still sees every document (cross-document lists and "same list?"
        # answers stay consistent); records of reused documents are not rebuilt or re-read.
        self.plan = build_structure_plan(self.documents, doclings, self.workspace, decisions)
        write_json(self.root / "structure" / "plan.json", {
            **self.plan.report(), "candidates": self.plan.candidates,
            "questions": [q.model_dump(mode="json") for q in self.plan.questions],
            "schema": self.plan.schema.model_dump(mode="json") if self.plan.schema else None})
        needs = self.plan.needs_model
        self.fallback = [key for key in needs if key not in self.reused] if self.model_enabled else []
        names = {doc.source.document_id: doc.source.filename for doc in self.documents}
        self.structure_report = {
            **self.plan.report(), "model_enabled": self.model_enabled,
            "documents_for_model": self.fallback,
            "documents_without_model": [] if self.model_enabled else [
                {"document_id": key, "filename": names.get(key)} for key in needs]}
        self.metadata(structure=self.structure_report)
        self.metadata(document_reuse={"reused": len(self.reused), "processed": len(changed),
                                      "model_calls_saved": sum(item[1] for item in self.reused.values())
                                      + (self.saved_discovery["calls"] if self.saved_discovery else 0)})
        if self.plan.schema is None and not self.fallback and self.cached_schema is None:
            raise PipelineError("empty" if self.model_enabled else "needs_model")

    def discover(self):
        """WP119: the model discovers collections only for documents structure did not cover."""
        if not self.documents:
            self._load_documents()
        structure = self.plan.schema if self.plan else None
        fallback = [doc for doc in self.documents if doc.source.document_id in self.fallback]
        model_schema = None
        if fallback:
            resolved = self.guard()
            self.measurements["options"] = {
                "reasoning_effort": resolved.reasoning_effort, "max_tokens": resolved.max_tokens,
                "extraction_concurrency": self.concurrency,
                "grouped_passes": get_settings().records_extraction_grouped_passes,
            }
            self.sources_unchanged()
            self.publication_unchanged()
            covered = {key: report.covered for key, report in self.plan.documents.items()}
            reduced = [doc.model_copy(update={"context": reduced_context(
                doc.context, covered.get(doc.source.document_id, []))}) for doc in fallback]
            chat = model_client(DiscoveryClient, resolved, self.guard, self.transport,
                                self.account("discover"))
            checked = CheckedDiscovery(chat, self.documents, self.root)
            try:
                model_schema = discover(reduced, self.workspace, checked, existing=structure)
                self.schema_review = checked.needs_review
                self.unverified = checked.unverified
            finally:
                chat.close()
        self.schema = combine_schemas(structure, model_schema)
        if self.schema is None and self.cached_schema is not None:
            return  # No new definitions; accept_schema uses the published contract directly.
        self.schema.sources = source_pins(self.documents, self.workspace)
        update_coverage(self.schema, self.documents)
        write_proposal(self.root / "schema", self.schema, self.documents)
        for pin in self.schema.sources:
            doc = next(d for d in self.documents if d.source.document_id == pin.document_id)
            write_json(source_directory(self.root / "schema", pin) / "source.json",
                       doc.source.model_dump(mode="json"))

    # KULLANILMIYOR (karar 18, WP119): model her belgenin bütün içeriğinden liste buluyordu.
    def _discover_before_wp119(self):
        resolved = self.guard()
        self.measurements["options"] = {
            "reasoning_effort": resolved.reasoning_effort, "max_tokens": resolved.max_tokens,
            "extraction_concurrency": self.concurrency,
            "grouped_passes": get_settings().records_extraction_grouped_passes,
        }
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
        chat = model_client(DiscoveryClient, resolved, self.guard, self.transport,
                            self.account("discover"))
        checked = CheckedDiscovery(chat, self.documents, self.root)
        try:
            self.schema = discover(self.documents, self.workspace, checked)
            self.schema_review = checked.needs_review
            self.unverified = checked.unverified
        finally:
            chat.close()
        write_proposal(self.root / "schema", self.schema, self.documents)
        for pin in self.schema.sources:
            doc = next(d for d in self.documents if d.source.document_id == pin.document_id)
            write_json(source_directory(self.root / "schema", pin) / "source.json",
                       doc.source.model_dump(mode="json"))

    def accept_schema(self):
        """WP110: accept what verifies; set the rest aside for review instead of stopping."""
        if self.schema is None and self.cached_schema is not None:
            self._accepted_update_schema()
            return
        schema = self.schema
        blocks = {doc.source.document_id: _blocks(doc.context) for doc in self.documents}
        set_aside, accepted = [], {}
        for collection in schema.collections:
            rejected = []
            examples = verify_examples(collection, blocks, rejected)
            supported = {v.key for e in examples for v in e.values}
            failed = {item.field for item in rejected}
            keep = set()
            for field in collection.fields:
                if collection.review_state not in {"proposed", "needs_review"}:
                    reason = "unverified"
                elif field.alternatives or field.review_state != "proposed":
                    reason = "alternatives"
                elif field.key in failed or field.key not in supported:
                    reason = "unverified"
                else:
                    keep.add(field.key)
                    continue
                set_aside.append(_review_item(collection, field, reason))
            proposed = {f.key for f in collection.fields} | {
                FIELD_SYNONYMS.get(f.key, f.key) for raw, f in self.unverified
                if raw.key in {collection.key, *collection.aliases}}
            names = proposed & set(IDENTITY_FIELDS)
            if names and not keep & names:
                # Without its verified name a record cannot be told apart; set the collection aside.
                keep = set()
            if keep:
                accepted[collection.key] = keep
            else:
                set_aside = [item for item in set_aside if item["collection"] != collection.key]
                set_aside.append(_review_item(collection, None, "unverified"))
        # Definitions that discovery could not verify never reached the proposal; list them as well.
        for raw, field in self.unverified:
            target = next((c for c in schema.collections if raw.key in {c.key, *c.aliases}), None)
            key = FIELD_SYNONYMS.get(field.key, field.key)
            if target and (target.key not in accepted or key in accepted[target.key] or any(
                    item["collection"] == target.key and item["field"] == key for item in set_aside)):
                continue
            item = _review_item(raw, field if target else None, "unverified")
            if item not in set_aside:
                set_aside.append(item)
        if not accepted:
            # Nothing verifiable remains: stop as before (needs_review, or empty without any proposal).
            if set_aside:
                self.metadata(schema_needs_review=set_aside)
            if not schema.collections:
                raise PipelineError("schema_review" if self.schema_review or schema.rejected else "empty")
            raise PipelineError("schema_review")
        # Nothing is removed from the proposal: set-aside parts stay there as needs_review.
        # The rule accepts definitions only, never record values.
        for collection in schema.collections:
            if collection.key not in accepted:
                collection.review_state = "needs_review"
                continue
            collection.review_state = "accepted"
            for field in collection.fields:
                if field.key in accepted[collection.key]:
                    field.review_state = "accepted"
                else:
                    field.review_state = "needs_review"
        write_json(self.root / "schema" / "schema.proposed.json", schema.model_dump(mode="json"))
        accepting = schema.model_copy(deep=True)
        accepting.collections = [c for c in accepting.collections if c.key in accepted]
        for collection in accepting.collections:
            collection.fields = [f for f in collection.fields if f.key in accepted[collection.key]]
        write_json(self.root / "schema" / "schema.accepting.json", accepting.model_dump(mode="json"))
        try:
            self.schema = accept_schema(self.root / "schema" / "schema.accepting.json", self.root / "schema")
        except ValueError:
            raise PipelineError("schema_review") from None
        self.metadata(schema_acceptance={
            "reviewer": "rule:u1-verified-schema",
            "reason": "Her alanın tipi ve sabit kaynak alıntısı doğrulandı; alternatif tanım yok.",
            "version": self.schema.version,
            "collections": [c.key for c in self.schema.collections],
            "set_aside": len(set_aside),
        }, schema_needs_review=set_aside)
        self.runtime = load_runtime(self.root / "schema" / f"schema.v{self.schema.version}.json")
        if self.cached_schema is not None:
            self._accepted_update_schema()

    # KULLANILMIYOR (karar 18, WP110): doğrulanamayan tek bir alan bütün işi durduruyordu.
    def _accept_schema_before_wp110(self):
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

    def _structure_result(self, doc):
        """Structure candidates of one document, verified against the accepted contract."""
        raw = (self.plan.candidates if self.plan else {}).get(doc.source.document_id)
        if not raw:
            return None
        records = []
        for record in raw["records"]:
            if record["type"] not in self.runtime.models:
                continue  # Set aside for review at schema acceptance.
            fields = self.runtime.models[record["type"]][1].model_fields
            records.append({"type": record["type"],
                            **{key: record.get(key, []) for key in fields}})
        if not records:
            return None
        result = verify_response(json.dumps({"records": records}, ensure_ascii=False), doc.context,
                                 doc.source.document_id, doc.source.lang, runtime=self.runtime)
        for record in result.records:
            # Distinct from model ordinals (document:type:N) of the same document.
            record.id = record.id.rsplit(":", 1)[0] + ":s" + record.id.rsplit(":", 1)[1]
        return result

    def extract(self):
        """WP119: structure records for every document; the model only reads what they left out."""
        structure = {doc.source.document_id: self._structure_result(doc) for doc in self.documents
                     if doc.source.document_id not in self.reused}
        fallback = [doc for doc in self.documents if doc.source.document_id in self.fallback]
        plans, runs, retried = {}, [], 0
        if fallback:
            chat = model_client(ChatClient, self.guard(), self.guard, self.transport,
                                self.account("extract"))
            try:
                covered = {key: report.covered for key, report in self.plan.documents.items()}
                for doc in fallback:
                    self.guard()
                    usage = ExtractionUsage()
                    context = reduced_context(doc.context, covered.get(doc.source.document_id, []))
                    run = ExtractionRun(context, doc.source.document_id, doc.source.lang, chat,
                                        concurrency=self.concurrency, usage=usage, runtime=self.runtime,
                                        grouped_passes=get_settings().records_extraction_grouped_passes)
                    plans[doc.source.document_id] = len(run.plan)
                    runs.append((doc, usage, run.run()))
                # Model/network failures left after the client's own retries get one more try here.
                for _doc, _usage, run in runs:
                    if failed := run.failed:
                        self.guard()
                        retried += len(failed)
                        run.run(failed)
            finally:
                chat.close()
        model = {doc.source.document_id: (usage, run.result()) for doc, usage, run in runs}
        rejected_fields, failed_sections = {}, []
        counts = Counter()
        for doc in self.documents:
            key = doc.source.document_id
            if key in self.reused:
                raw = {**self.reused[key][0], "workspace_schema": self.runtime.schema}
                # A reviewed "same list" answer may have retired the extraction's old key.
                aliases = {alias: c["key"] for c in self.runtime.schema["collections"]
                           for alias in c.get("aliases", []) if alias not in self.runtime.models}
                for record in raw["records"]:
                    record["type"] = aliases.get(record["type"], record["type"])
                # A list set aside since then is skipped, as in _structure_result.
                raw["records"] = [r for r in raw["records"] if r["type"] in self.runtime.models]
                result = self.runtime.result.model_validate(raw)
                path = self.root / "records" / sha256(key.encode()).hexdigest()
                write_json(path / "records.json", result.model_dump(mode="json", exclude_none=True))
                continue
            usage, from_model = model.get(key, (None, None))
            from_structure = structure.get(key)
            counts["structure"] += len(from_structure.records) if from_structure else 0
            counts["model"] += len(from_model.records) if from_model else 0
            parts = [part for part in (from_structure, from_model) if part is not None]
            records = [record for part in parts for record in part.records]
            result = self.runtime.result(
                document_id=key, lang=doc.source.lang,
                records=_coalesce_document_records(records, doc.source.lang, self.runtime),
                rejected=[item for part in parts for item in part.rejected],
                failures=from_model.failures if from_model else [])
            path = self.root / "records" / sha256(key.encode()).hexdigest()
            if usage is not None:
                doc.source.usage = usage
            write_json(path / "source.json", doc.source.model_dump(mode="json"))
            write_json(path / "records.json", result.model_dump(mode="json", exclude_none=True))
            if reasons := Counter(item.reason for item in result.rejected):
                rejected_fields[key] = dict(sorted(reasons.items()))
            failed_sections.extend({"document_id": key, **failure.model_dump(mode="json")}
                                   for failure in result.failures)
        total = sum(plans.values())
        self.structure_report.update(records_from_structure=counts["structure"],
                                     records_from_model=counts["model"],
                                     documents_used_model=sorted(model))
        self.metadata(extraction_plans=plans, extraction_concurrency=self.concurrency,
                      rejected_fields=rejected_fields, failed_sections=failed_sections,
                      extraction_sections={"total": total, "failed": len(failed_sections),
                                           "retried": retried},
                      structure=self.structure_report)
        if total and len(failed_sections) * 100 > total * lifecycle.MAX_FAILED_SECTIONS_PERCENT:
            raise PipelineError("sections_failed")
        self.results = load_records(self.root / "records", runtime=self.runtime)
        discovery = {"documents": list(self.fallback), "calls": sum(
            call["stage"] == "discover" for call in self.measurements["calls"])}
        if not self.fallback and self.saved_discovery:
            discovery = self.saved_discovery
        write_json(self.root / "reuse.json", {"discovery": discovery, "documents": {
            doc.source.document_id: {
                "content_sha256": doc.source.content_sha256,
                "knowledge_revision_id": doc.source.knowledge_revision_id,
                "model_calls": (self.reused[doc.source.document_id][1]
                                if doc.source.document_id in self.reused else
                                len(doc.source.usage.calls) if doc.source.usage else 0),
                "model_pending": (self.reused[doc.source.document_id][2]
                                  if doc.source.document_id in self.reused else
                                  doc.source.document_id in (self.plan.needs_model if self.plan else [])
                                  and doc.source.document_id not in self.fallback),
            } for doc in self.documents}})
        if not any(result.records for result in self.results) and self.base is None:
            raise PipelineError("empty" if self.model_enabled else "needs_model")

    # KULLANILMIYOR (karar 18, WP119): model her belgenin bütün içeriğinden kayıt çıkarıyordu.
    def _extract_before_wp119(self):
        """WP110: rejected fields are reported; failed sections are retried once, then reported."""
        chat = model_client(ChatClient, self.guard(), self.guard, self.transport,
                            self.account("extract"))
        plans, runs, retried = {}, [], 0
        try:
            for doc in self.documents:
                self.guard()
                usage = ExtractionUsage()
                run = ExtractionRun(doc.context, doc.source.document_id, doc.source.lang, chat,
                                    concurrency=self.concurrency, usage=usage, runtime=self.runtime,
                                    grouped_passes=get_settings().records_extraction_grouped_passes)
                plans[doc.source.document_id] = len(run.plan)
                runs.append((doc, usage, run.run()))
            # Model/network failures left after the client's own retries get one more try here.
            for _doc, _usage, run in runs:
                if failed := run.failed:
                    self.guard()
                    retried += len(failed)
                    run.run(failed)
        finally:
            chat.close()
        rejected_fields, failed_sections = {}, []
        for doc, usage, run in runs:
            result = run.result()
            path = self.root / "records" / sha256(doc.source.document_id.encode()).hexdigest()
            doc.source.usage = usage
            write_json(path / "source.json", doc.source.model_dump(mode="json"))
            write_json(path / "records.json", result.model_dump(mode="json", exclude_none=True))
            if counts := Counter(item.reason for item in result.rejected):
                rejected_fields[doc.source.document_id] = dict(sorted(counts.items()))
            failed_sections.extend({"document_id": doc.source.document_id,
                                    **failure.model_dump(mode="json")} for failure in result.failures)
        total = sum(plans.values())
        self.metadata(extraction_plans=plans, extraction_concurrency=self.concurrency,
                      rejected_fields=rejected_fields, failed_sections=failed_sections,
                      extraction_sections={"total": total, "failed": len(failed_sections),
                                           "retried": retried})
        if len(failed_sections) * 100 > total * lifecycle.MAX_FAILED_SECTIONS_PERCENT:
            raise PipelineError("sections_failed")
        self.results = load_records(self.root / "records", runtime=self.runtime)
        if not any(result.records for result in self.results):
            raise PipelineError("empty")

    # KULLANILMIYOR (karar 18, WP110): tek reddedilen alan ya da tek başarısız bölüm işi durduruyordu.
    def _extract_before_wp110(self):
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
        """WP111 (karar 20): verified agreeing values are accepted by a recorded rule; the rest wait."""
        merge_matches(self.root / "records", self.results, self.matches, self.root / "merged",
                      self.workspace, "u1_" + self.job_id, "strong")
        self.revision = load_revision((self.root / "merged" / "merge_revision.json").read_bytes())
        if not self.revision.records and self.base is None:
            raise PipelineError("empty")
        self.revision, counts = carry_forward(self.revision, self.base, {
            doc.source.document_id: doc.context for doc in self.documents})
        self.metadata(carry_forward=counts)
        self.revision, audit = apply_review_rules(self.revision)
        self.metadata(field_review_audit=audit, field_review_counts=review_counts(audit))
        # WP119: unsure list groupings become "same list?" questions; earlier answers are kept.
        if self.plan is not None:
            present = set(self.runtime.collections.values())
            revision = self.revision.model_copy(deep=True)
            revision.collection_merges = [
                q for q in self.plan.questions
                if q.left.collection in present and q.right.collection in present]
            revision.collection_merge_decisions = list(self.remembered_decisions)
            self.revision = MergeRevision.model_validate_json(revision.model_dump_json(round_trip=True))
            self.structure_report["collection_merge_questions"] = len(revision.collection_merges)
            self.metadata(structure=self.structure_report)
        write_json(self.root / "merged" / "merge_revision.json", self.revision.model_dump(mode="json"))

    # KULLANILMIYOR (karar 18, WP111): her doğrulanmış tek kaynaklı değer de insan onayı bekliyordu.
    def _merge_before_wp111(self):
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
        for stage in self.stages:
            self.guard()
            stamp = lifecycle.now()
            def begin(job, stage=stage, stamp=stamp):
                job.update(stage=stage, message=self.labels[stage], heartbeat_at=stamp,
                           stage_deadline=(datetime.now(UTC) + timedelta(
                               seconds=self.stage_timeouts[stage])).isoformat())
                job["stages"][stage].update(status="running", started_at=stamp)
            if not jobs.change(self.workspace, self.job_id, begin, {"running"}):
                raise PipelineError("worker_stale")
            started = time.monotonic()
            try:
                getattr(self, stage)()
            finally:
                calls = [call for call in self.measurements["calls"] if call["stage"] == stage]
                values = {"wall_seconds": time.monotonic() - started, "calls": len(calls),
                          "retries": sum(call["attempt"] > 1 for call in calls)}
                for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens"):
                    reported = [call[key] for call in calls if key in call]
                    values[key] = sum(reported) if reported else None
                    values["missing_" + key + "_calls"] = len(calls) - len(reported)
                self.measurements["stages"][stage] = values
                # publish() writes done inside its lock; persist its duration afterwards too.
                jobs.change(self.workspace, self.job_id,
                            lambda job: job["metadata"].update(speed=self.measurements),
                            {"running", "done", "failed"})
            if stage == "publish":
                return  # Publication read verification and terminal write share its lock.
            self.guard()
            def complete(job, stage=stage):
                job["stages"][stage].update(status="done", finished_at=lifecycle.now())
                job["completed_stages"] += 1
            if not jobs.change(self.workspace, self.job_id, complete, {"running"}):
                raise PipelineError("worker_stale")


def process_job(job_id, transport=None, document_loader=None, docling_loader=None):
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
        if job.get("kind") == "field_fill":
            from .field_fill_job import FieldFillJob

            FieldFillJob(job, transport).run()
        else:
            Pipeline(job, transport, document_loader, docling_loader=docling_loader).run()
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
