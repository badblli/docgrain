"""Read the current published revisions without mutating API state."""

import httpx


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

    def output(self, revision_id: str, filename: str) -> str | dict:
        response = self.client.get(
            f"/v1/knowledge/revisions/{revision_id}/outputs/{filename}"
        )
        response.raise_for_status()
        return response.json() if filename.endswith(".json") else response.text


def build_context(api: PublishedAPI, workspace_id: str) -> tuple[str, dict[str, str]]:
    blocks = []
    revisions = {}
    for document in api.documents(workspace_id):
        document_id = document["id"]
        revision_id = api.revision_id(document_id)
        content = api.output(revision_id, "canonical.md")
        revisions[document_id] = revision_id
        blocks.append(f"[{document_id}] {document['filename']}\n{content}")
    if not blocks:
        raise ValueError(f"workspace {workspace_id} has no published documents")
    return "\n\n".join(blocks), revisions
