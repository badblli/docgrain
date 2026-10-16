"""Opt-in targeted extraction for a user-added field."""

from hashlib import sha256

import httpx
from docgrain_records.discovery_models import DiscoveryDocument, WorkspaceSchema
from docgrain_records.discovery_store import source_directory
from docgrain_records.model import ChatClient
from docgrain_records.targeted_fill import fill_field

from .workspace_settings import get_workspace_model, resolve_workspace_model


class _GuardTransport(httpx.BaseTransport):
    def __init__(self, workspace, version):
        self.workspace = workspace
        self.version = version
        self.inner = httpx.HTTPTransport()

    def handle_request(self, request):
        resolve_workspace_model(self.workspace, self.version)
        return self.inner.handle_request(request)

    def close(self):
        self.inner.close()


# KULLANILMIYOR (karar 18, WP120): HTTP isteğinde alan dolduran eski yol.
def fill_new_field(store, revision, collection, field):
    settings = get_workspace_model(revision.workspace_id)
    if not settings["enabled"]:
        return revision, "Model kapalı; alanı elle doldurabilirsiniz."
    resolved = resolve_workspace_model(revision.workspace_id)
    # The source job's immutable contexts are kept beside the publication store.
    ancestor = revision.parent_id
    job_id = None
    while ancestor:
        manifest = store.manifest(revision.workspace_id, ancestor)
        job_id = manifest.get("record_job_id")
        if job_id:
            break
        ancestor = store._source(revision.workspace_id, ancestor).parent_id
    if not job_id:
        raise ValueError("pinned document contexts unavailable")
    root = store._path(revision.workspace_id) / "runtime" / sha256(job_id.encode()).hexdigest() / "schema"
    schema = WorkspaceSchema.model_validate(revision.workspace_schema)
    documents = []
    for source in schema.sources:
        context = (source_directory(root, source) / "context.md").read_text(encoding="utf-8")
        if sha256(context.encode()).hexdigest() != source.context_sha256:
            raise ValueError("pinned document context changed")
        documents.append(DiscoveryDocument(source=source.model_dump(exclude={"context_sha256"}),
                                           context=context))
    chat = ChatClient(resolved.base_url, resolved.model, resolved.api_key or "local-profile",
                      transport=_GuardTransport(revision.workspace_id, resolved.settings_version),
                      reasoning_effort=resolved.reasoning_effort, max_tokens=resolved.max_tokens)
    if not resolved.api_key:
        del chat.client.headers["Authorization"]
    try:
        filled, rejected = fill_field(revision, collection, field, documents, chat)
    finally:
        chat.close()
    resolve_workspace_model(revision.workspace_id, resolved.settings_version)
    note = ("Belgelerde doğrulanabilen değerler eklendi; diğerleri boş kaldı."
            if not rejected else "Doğrulanamayan belge önerileri eklenmedi.")
    return filled, note


def load_pinned_contexts(store, revision, context_job_id):
    """Read the original full job's immutable Docling-derived contexts, checking every hash."""
    root = (store._path(revision.workspace_id) / "runtime" /
            sha256(context_job_id.encode()).hexdigest() / "schema")
    schema = WorkspaceSchema.model_validate(revision.workspace_schema)
    if not schema.sources:
        raise ValueError("pinned contexts unavailable")
    documents = []
    for source in schema.sources:
        context = (source_directory(root, source) / "context.md").read_text(encoding="utf-8")
        if sha256(context.encode()).hexdigest() != source.context_sha256:
            raise ValueError("pinned context changed")
        documents.append(DiscoveryDocument(
            source=source.model_dump(exclude={"context_sha256"}), context=context))
    return documents


def fill_from_contexts(revision, collection, field, documents, resolved, guard, transport=None,
                       on_usage=None):
    """Worker-only model I/O; recheck the job and model opt-in for every physical request."""
    class GuardedTransport(httpx.BaseTransport):
        def __init__(self):
            self.inner = transport or httpx.HTTPTransport()

        def handle_request(self, request):
            guard()
            return self.inner.handle_request(request)

        def close(self):
            self.inner.close()

    guard()
    chat = ChatClient(resolved.base_url, resolved.model, resolved.api_key or "local-profile",
                      transport=GuardedTransport(), reasoning_effort=resolved.reasoning_effort,
                      max_tokens=resolved.max_tokens, on_usage=on_usage)
    if not resolved.api_key:
        del chat.client.headers["Authorization"]
    try:
        filled, rejected = fill_field(revision, collection, field, documents, chat)
    finally:
        chat.close()
    guard()
    note = ("Doğrulanamayan belge önerileri eklenmedi." if rejected else
            "Belgelerde doğrulanabilen değerler eklendi; diğerleri boş kaldı.")
    return filled, note, rejected
