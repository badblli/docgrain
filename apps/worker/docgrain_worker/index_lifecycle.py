"""Explicit synchronous index refresh; no automatic ingestion or provider selection."""

from docgrain_api.canonical_repository import CanonicalConflict
from docgrain_domain.canonical.chunking import derive_chunk_set
from docgrain_domain.canonical.indexing import (
    Embedder,
    IndexEntry,
    IndexGeneration,
    IndexSpec,
    embedding_cache_key,
    entry_refs,
    generation_revision,
)


def refresh_index(repository, revision_id: str, spec: IndexSpec, embedder: Embedder, *,
                  expected_generation_id: str | None, full: bool = False) -> tuple[IndexGeneration, bool]:
    spec = IndexSpec.model_validate(spec.model_dump(mode="json"))
    snapshot = repository.get_snapshot(revision_id)
    if snapshot is None:
        raise ValueError("canonical revision not found")
    chunk_set = derive_chunk_set(snapshot, spec.chunking)
    embedding, indexing = generation_revision(chunk_set, spec, expected_generation_id, full)
    with repository.build_lock(snapshot.workspace_id, snapshot.document_id):
        existing = repository.get_generation(indexing.id)
        if existing:
            return existing, False
        previous = repository.get_active(snapshot.workspace_id, snapshot.document_id, spec.name)
        if (previous.revision.id if previous else None) != expected_generation_id:
            raise CanonicalConflict("index head changed concurrently")
        if repository.get_heads(snapshot.document_id)[0] != revision_id:
            raise CanonicalConflict("target canonical revision is no longer latest")
        entries, embedded, reused = [], [], []
        for chunk in chunk_set.chunks:
            key = embedding_cache_key(snapshot.workspace_id, snapshot.document_id, spec.embedding, chunk.content_sha256)
            vector = None if full else repository.get_checkpoint(key)
            if vector is None:
                vector = spec.embedding.validate_vector(embedder.embed(chunk.retrieval_text, spec.embedding))
                repository.checkpoint(key, vector)
                embedded.append(chunk.object_ref.object_id)
            else:
                vector = spec.embedding.validate_vector(vector)
                reused.append(chunk.object_ref.object_id)
            embedding_ref, index_ref = entry_refs(chunk, embedding, indexing)
            entries.append(IndexEntry(chunk=chunk, embedding_ref=embedding_ref, index_ref=index_ref, vector=vector))
        current_ids = {entry.chunk.object_ref.object_id for entry in entries}
        removed = [e.chunk.object_ref.object_id for e in previous.entries if e.chunk.object_ref.object_id not in current_ids] if previous else []
        generation = IndexGeneration(spec=spec, base_id=expected_generation_id, full=full, chunk_set=chunk_set,
                                     embedding_revision=embedding, revision=indexing, entries=entries,
                                     embedded_chunk_ids=embedded, reused_chunk_ids=reused, removed_chunk_ids=removed)
        return generation, repository.publish(generation)
