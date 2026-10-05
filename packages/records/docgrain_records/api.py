"""Read one pinned compact context; no API/worker changes or publication writes."""

from urllib.parse import quote

import httpx
from docgrain_domain.canonical.ai_output import context_projection, project_ai
from docgrain_domain.canonical.chunking import ChunkingSpec, derive_chunk_set
from docgrain_domain.canonical.models import CanonicalKnowledgeSnapshot
from pydantic import TypeAdapter, ValidationError

from .models import Language


def load_context(client: httpx.Client, document_id: str, lang: str | None = None) -> tuple[str, str]:
    response = client.get(f"/v1/documents/{quote(document_id, safe='')}/knowledge")
    response.raise_for_status()
    knowledge = response.json()
    snapshot = knowledge.get("snapshot") or {}
    revision = knowledge.get("latest_revision_id")
    if not revision or knowledge.get("document_id") != document_id or snapshot.get("document_id") != document_id:
        raise ValueError("document has no matching normalized revision")
    if snapshot.get("knowledge_revision", {}).get("id") != revision:
        raise ValueError("normalized revision does not match the document head")
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
    return context, language
