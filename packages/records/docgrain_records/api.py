"""Read one pinned compact context; no API/worker changes or publication writes."""

from urllib.parse import quote

import httpx
from docgrain_domain.canonical.ai_output import context_projection, project_ai
from docgrain_domain.canonical.chunking import ChunkingSpec, derive_chunk_set
from docgrain_domain.canonical.models import CanonicalKnowledgeSnapshot
from pydantic import Field, TypeAdapter, ValidationError

from .models import ExtractionUsage, Language, StrictModel, Text


class SourceMetadata(StrictModel):
    """The canonical snapshot pin used for this extraction artifact."""

    document_id: Text
    workspace_id: Text
    knowledge_revision_id: Text
    source_version_id: Text
    content_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    lang: Language
    usage: ExtractionUsage | None = None


def load_context(client: httpx.Client, document_id: str, lang: str | None = None) -> tuple[str, str]:
    context, language, _ = load_context_bundle(client, document_id, lang, require_pins=False)
    return context, language


def load_context_bundle(client: httpx.Client, document_id: str, lang: str | None = None,
                        *, require_pins: bool = True) -> tuple[str, str, SourceMetadata | None]:
    """Fetch one context and its source pin from the same knowledge response."""
    response = client.get(f"/v1/documents/{quote(document_id, safe='')}/knowledge")
    response.raise_for_status()
    knowledge = response.json()
    snapshot = knowledge.get("snapshot") or {}
    revision = knowledge.get("latest_revision_id")
    if not revision or knowledge.get("document_id") != document_id or snapshot.get("document_id") != document_id:
        raise ValueError("document has no matching normalized revision")
    if snapshot.get("knowledge_revision", {}).get("id") != revision:
        raise ValueError("normalized revision does not match the document head")
    source = snapshot.get("source_version") or {}
    revision_pin = snapshot.get("knowledge_revision") or {}
    if ((source.get("document_id") not in {None, document_id})
        or (revision_pin.get("source_version_id") not in {None, source.get("id")})
        or (source.get("workspace_id") not in {None, snapshot.get("workspace_id")})):
        raise ValueError("normalized source pin does not match the document revision")
    if require_pins and (
        source.get("document_id") != document_id
        or source.get("workspace_id") != snapshot.get("workspace_id")
        or revision_pin.get("document_id") != document_id
        or revision_pin.get("workspace_id") != snapshot.get("workspace_id")
        or revision_pin.get("source_version_id") != source.get("id")
    ):
        raise ValueError("normalized source pin is incomplete")
    metadata = snapshot.get("metadata") or {}
    language = lang or metadata.get("lang") or metadata.get("language") or "und"
    try:
        TypeAdapter(Language).validate_python(language)
    except ValidationError as exc:
        raise ValueError("source language is invalid; specify --lang") from exc
    response = client.get(
        f"/v1/knowledge/revisions/{quote(revision, safe='')}/outputs/context.md",
    )
    if response.status_code == 404:
        # Same deterministic fallback as evaluation's compact mode, never canonical.md.
        try:
            canonical = CanonicalKnowledgeSnapshot.model_validate(snapshot)
        except ValidationError as exc:
            raise ValueError("normalized document does not match the canonical schema") from exc
        chunks = derive_chunk_set(canonical, ChunkingSpec())
        context = context_projection(project_ai(canonical, chunks))
    else:
        response.raise_for_status()
        context = response.text
    if not context.strip():
        raise ValueError("source context is empty")
    pin = None
    if require_pins:
        try:
            pin = SourceMetadata(
                document_id=document_id, workspace_id=snapshot.get("workspace_id"),
                knowledge_revision_id=revision, source_version_id=source.get("id"),
                content_sha256=source.get("content_sha256"), lang=language,
            )
        except ValidationError as exc:
            raise ValueError("normalized source pin is missing or invalid") from exc
    return context, language, pin
