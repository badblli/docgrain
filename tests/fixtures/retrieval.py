"""Explicit synthetic materialized generations for ranking correctness fixtures."""

from docgrain_domain.canonical.chunking import derive_chunk_set
from docgrain_domain.canonical.indexing import (
    IndexEntry,
    IndexGeneration,
    entry_refs,
    generation_revision,
)
from docgrain_domain.canonical.retrieval import DocumentView, context_projection

from tests.fixtures.incremental import index_spec
from tests.unit.test_m2c_chunking import rich_snapshot


def view(snapshot=None, vector_for=None):
    snapshot = snapshot or rich_snapshot()
    spec = index_spec()
    chunks = derive_chunk_set(snapshot, spec.chunking)
    embedding, indexing = generation_revision(chunks, spec, None, False)
    entries = []
    for chunk in chunks.chunks:
        embedding_ref, index_ref = entry_refs(chunk, embedding, indexing)
        vector = vector_for(chunk) if vector_for else [1.0, 0.0]
        entries.append(IndexEntry(chunk=chunk, embedding_ref=embedding_ref, index_ref=index_ref, vector=vector))
    generation = IndexGeneration(spec=spec, base_id=None, chunk_set=chunks, embedding_revision=embedding,
                                 revision=indexing, entries=entries, embedded_chunk_ids=[e.chunk.object_ref.object_id for e in entries],
                                 reused_chunk_ids=[], removed_chunk_ids=[])
    return DocumentView(snapshot=snapshot, generation=generation, context=context_projection(snapshot))
