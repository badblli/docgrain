"""Read the current published revisions without mutating API state."""

import httpx
from docgrain_domain.canonical.ai_output import context_projection, project_ai
from docgrain_domain.canonical.chunking import ChunkingSpec, derive_chunk_set
from docgrain_domain.canonical.models import CanonicalKnowledgeSnapshot


class PublishedAPI:
    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=30)
        self.owns_client = client is None

    def close(self):
        if self.owns_client:
            self.client.close()

    def documents(self, workspace_id: str | None = None) -> list[dict]:
        documents = []
        offset = 0
        while True:
            response = self.client.get("/v1/documents", params={"limit": 50, "offset": offset})
            response.raise_for_status()
            batch = response.json()
            documents.extend(
                item["document"] for item in batch
                if workspace_id is None or item["document"]["workspace_id"] == workspace_id
            )
            if len(batch) < 50:
                return documents
            offset += 50

    def revision_id(self, document_id: str) -> str:
        response = self.client.get(f"/v1/documents/{document_id}/knowledge")
        response.raise_for_status()
        return response.json()["latest_revision_id"]

    def knowledge(self, document_id: str) -> dict:
        response = self.client.get(f"/v1/documents/{document_id}/knowledge")
        response.raise_for_status()
        return response.json()

    def output(self, revision_id: str, filename: str) -> str | dict:
        response = self.client.get(
            f"/v1/knowledge/revisions/{revision_id}/outputs/{filename}"
        )
        response.raise_for_status()
        return response.json() if filename.endswith(".json") else response.text


def build_context(api: PublishedAPI, workspace_id: str) -> tuple[str, dict[str, str]]:
    context, revisions, _ = build_context_details(api, workspace_id, "canonical")
    return context, revisions


def build_context_details(api: PublishedAPI, workspace_id: str,
                          context_mode: str = "canonical") -> tuple[str, dict[str, str], dict[str, str]]:
    blocks = []
    revisions = {}
    sources = {}
    for document in api.documents(workspace_id):
        document_id = document["id"]
        knowledge = api.knowledge(document_id)
        revision_id = knowledge["latest_revision_id"]
        if context_mode == "compact":
            try:
                content = api.output(revision_id, "context.md")
                sources[document_id] = "published_context.md"
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                snapshot = CanonicalKnowledgeSnapshot.model_validate(knowledge["snapshot"])
                chunks = derive_chunk_set(snapshot, ChunkingSpec())
                content = context_projection(project_ai(snapshot, chunks))
                sources[document_id] = "local_projection"
        else:
            content = api.output(revision_id, "canonical.md")
            sources[document_id] = "published_canonical.md"
        revisions[document_id] = revision_id
        blocks.append(f"[{document_id}] {document['filename']}\n{content}")
    if not blocks:
        raise ValueError(f"workspace {workspace_id} has no published documents")
    return "\n\n".join(blocks), revisions, sources
