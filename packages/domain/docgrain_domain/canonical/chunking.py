"""Fixed-version structure-first retrieval derivation from canonical JSON only."""

from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from typing import Literal

from pydantic import Field

from .lifecycle import DerivedRevision, chunk_id
from .lineage import (
    ChunkContext,
    ChunkOmission,
    ChunkPayload,
    ChunkSource,
    DerivedManifest,
    LineageEdge,
    ObjectRef,
    contextualize_chunk,
)
from .locations import StrictModel
from .models import (
    AssetNode,
    CanonicalKnowledgeSnapshot,
    ChartNode,
    DocumentNode,
    ListNode,
    SchemaEntity,
    SectionNode,
    TableNode,
    TextBlock,
)


class ChunkingSpec(StrictModel):
    strategy: Literal["canonical-structure"] = "canonical-structure"
    strategy_version: Literal["1"] = "1"
    budget_unit: Literal["unicode-characters"] = "unicode-characters"
    max_chars: int = Field(default=1600, ge=64, le=32000)
    max_table_rows: int = Field(default=20, ge=1, le=1000)
    table_header_rows: dict[str, int] = Field(default_factory=dict)
    include_entities: bool = True


def _json(value, *, pretty=False):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      **({"indent": 2} if pretty else {"separators": (",", ":")}))


class ChunkSet(StrictModel):
    """Complete derivation, including a valid empty result; not a historical manifest."""

    revision: DerivedRevision
    chunks: list[ChunkPayload]
    chunk_omissions: list[ChunkOmission]

    def manifest(self) -> DerivedManifest:
        if not self.chunks:
            raise ValueError("canonical revision has no extractable chunk content")
        return DerivedManifest(schema_version="0.3.0", revision=self.revision,
                               objects=[chunk.object_ref for chunk in self.chunks],
                               edges=[LineageEdge(upstream=p, downstream=c.object_ref)
                                      for c in self.chunks for p in c.parents],
                               chunks=self.chunks, chunk_omissions=self.chunk_omissions)


def derive_chunks(snapshot: CanonicalKnowledgeSnapshot, spec: ChunkingSpec) -> DerivedManifest:
    return derive_chunk_set(snapshot, spec).manifest()


def derive_chunk_set(snapshot: CanonicalKnowledgeSnapshot, spec: ChunkingSpec) -> ChunkSet:
    """Pure derivation; legacy canonical snapshots can also be previewed without migration."""
    snapshot = CanonicalKnowledgeSnapshot.model_validate(snapshot.model_dump(mode="json"))
    spec = ChunkingSpec.model_validate(spec.model_dump(mode="json"))
    nodes = {node.id: node for node in snapshot.structure}
    for identity, count in spec.table_header_rows.items():
        node = nodes.get(identity)
        if not isinstance(node, TableNode) or not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= len(node.rows):
            raise ValueError("table header rows must name a table and an available nonnegative row count")
    revision = DerivedRevision.create(workspace_id=snapshot.workspace_id, document_id=snapshot.document_id,
                                       processing_revision_id=snapshot.knowledge_revision.id, stage="chunking",
                                       upstream_revision_ids=(snapshot.knowledge_revision.id,), strategy=spec.strategy,
                                       strategy_version=spec.strategy_version, configuration=spec.model_dump(mode="json"))
    chunks = []
    omissions = []
    ordinals = Counter()
    buffer = []
    buffer_context = []
    buffer_role = None

    def ref(item):
        return ObjectRef(kind="canonical", revision_id=snapshot.knowledge_revision.id, object_id=item.id)

    def context(item, kind, text):
        return ChunkContext(object_ref=ref(item), kind=kind, text=text,
                            evidence_ids=item.annotation.provenance.evidence_ids)

    def emit(kind, text, contexts, sources, *, fallback=False):
        parents = list({item.object_ref.key: item.object_ref for item in [*contexts, *sources]}.values())
        retrieval = contextualize_chunk(text, contexts)
        checksum = sha256(retrieval.encode()).hexdigest()
        keys = tuple(parent.object_id for parent in parents)
        ordinal = ordinals[keys]
        ordinals[keys] += 1
        identity = chunk_id(snapshot.document_id, list(keys), spec.strategy,
                            spec.strategy_version + ":" + revision.configuration_digest, ordinal, checksum)
        evidence = list(dict.fromkeys(r for item in [*contexts, *sources] for r in item.evidence_ids))
        chunks.append(ChunkPayload(object_ref=ObjectRef(kind="chunk", revision_id=revision.id, object_id=identity),
                                   kind=kind, order=len(chunks), ordinal=ordinal, text=text, retrieval_text=retrieval,
                                   content_sha256=checksum, character_count=len(retrieval), oversized=len(retrieval) > spec.max_chars,
                                   split_fallback=fallback, parents=parents, context=contexts, sources=sources, evidence_ids=evidence))

    def flush():
        nonlocal buffer, buffer_role
        if buffer:
            emit("text", "\n\n".join(piece[1] for piece in buffer), buffer_context,
                 [ChunkSource(object_ref=ref(piece[0]), kind="text", start=piece[2], end=piece[3],
                              evidence_ids=piece[0].annotation.provenance.evidence_ids) for piece in buffer],
                 fallback=any(piece[4] for piece in buffer))
        buffer = []
        buffer_role = None

    def text_node(node, contexts):
        nonlocal buffer_context, buffer_role
        if not node.text:
            omissions.append(ChunkOmission(object_ref=ref(node), reason="empty_text"))
            return
        if buffer and (buffer_context != contexts or buffer_role != node.role):
            flush()
        prefix_size = len(contextualize_chunk("", contexts))
        # A very long heading can already exceed the budget; avoid one-character fragments.
        budget = spec.max_chars - prefix_size if prefix_size < spec.max_chars else spec.max_chars
        offset = 0
        split = len(node.text) > budget
        while offset < len(node.text):
            end = min(len(node.text), offset + budget)
            if end < len(node.text):
                boundary = max((i + 1 for i in range(offset, end) if node.text[i].isspace()), default=end)
                end = boundary
            piece = (node, node.text[offset:end], offset, end, split)
            joined = "\n\n".join([*(p[1] for p in buffer), piece[1]])
            if buffer and len(contextualize_chunk(joined, contexts)) > spec.max_chars:
                flush()
            buffer_context = contexts
            buffer_role = node.role
            buffer.append(piece)
            offset = end
            if offset < len(node.text):
                flush()

    def table_node(node, contexts):
        contexts = [*contexts, *([context(node, "table_caption", node.caption)] if node.caption else [])]
        header_count = spec.table_header_rows.get(node.id, 0)
        headers = node.rows[:header_count]

        def body(rows):
            return _json({"caption": node.caption, "header_rows": [cell_row(row) for row in headers],
                          "rows": [cell_row(row) for row in rows]})

        def sources(start, end):
            ranges = ([(0, header_count)] if header_count else []) + ([(start, end)] if end > start else [])
            return [ChunkSource(object_ref=ref(node), kind="rows", start=a, end=b,
                                evidence_ids=list(dict.fromkeys(r for row in node.rows[a:b] for cell in row
                                                               for r in (cell.annotation or node.annotation).provenance.evidence_ids)))
                    for a, b in ranges] or [ChunkSource(object_ref=ref(node), kind="whole",
                                                       evidence_ids=node.annotation.provenance.evidence_ids)]

        start = header_count
        rows = []
        for index, row in enumerate(node.rows[header_count:], start=header_count):
            if rows and (len(rows) >= spec.max_table_rows or len(contextualize_chunk(body([*rows, row]), contexts)) > spec.max_chars):
                emit("table", body(rows), contexts, sources(start, index))
                rows = []
                start = index
            rows.append(row)
        emit("table", body(rows), contexts, sources(start, len(node.rows)))

    def walk(identity, contexts):
        node = nodes[identity]
        if isinstance(node, (DocumentNode, SectionNode, ListNode)):
            flush()
            kind = node.kind
            heading = (node.title or "") if isinstance(node, DocumentNode) else (node.heading if isinstance(node, SectionNode)
                        else ("List: ordered" if node.ordered else "List: unordered"))
            nested = [*contexts, context(node, kind, heading)]
            for child in node.children:
                walk(child, nested)
            flush()
            if isinstance(node, SectionNode) and not node.children and node.heading:
                emit("text", node.heading, contexts, [ChunkSource(object_ref=ref(node), kind="whole",
                     evidence_ids=node.annotation.provenance.evidence_ids)])
        elif isinstance(node, TextBlock):
            text_node(node, contexts)
        elif isinstance(node, TableNode):
            flush()
            table_node(node, contexts)
        elif isinstance(node, (AssetNode, ChartNode)):
            flush()
            if node.description:
                emit("description", node.description, contexts, [ChunkSource(object_ref=ref(node), kind="whole",
                     evidence_ids=node.annotation.provenance.evidence_ids)])
            else:
                omissions.append(ChunkOmission(object_ref=ref(node), reason="no_description"))

    walk(snapshot.root_node_id, [])
    document_context = [context(nodes[snapshot.root_node_id], "document", nodes[snapshot.root_node_id].title or "")]
    for entity in snapshot.entities:
        if not isinstance(entity, SchemaEntity):
            omissions.append(ChunkOmission(object_ref=ref(entity), reason="legacy_entity"))
        elif entity.validation.status != "valid":
            omissions.append(ChunkOmission(object_ref=ref(entity), reason="invalid_entity"))
        elif entity.review_status != "accepted":
            omissions.append(ChunkOmission(object_ref=ref(entity), reason="unaccepted_entity"))
        elif not spec.include_entities:
            omissions.append(ChunkOmission(object_ref=ref(entity), reason="entity_disabled"))
        else:
            fields = sorted(entity.field_annotations)
            emit("entity", _json(entity.data, pretty=True) + "\n",
                 [*document_context, context(entity, "entity_label", entity.label)],
                 [ChunkSource(object_ref=ref(entity), kind="entity_fields", field_pointers=fields,
                              evidence_ids=list(dict.fromkeys(r for path in fields
                                                             for r in entity.field_annotations[path].provenance.evidence_ids)))])
    return ChunkSet(revision=revision, chunks=chunks, chunk_omissions=omissions)


def cell_row(row):
    """Keep source facts; formulas are never evaluated or headers guessed."""
    return [cell.model_dump(mode="json", exclude={"annotation"}) for cell in row]
