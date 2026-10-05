"""A format-neutral, fidelity-preserving pre-embedding projection; not semantic inference."""

import json
from hashlib import sha256
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from .chunking import ChunkingSpec, ChunkSet, derive_chunk_set
from .identity import canonical_json_bytes
from .lifecycle import DerivedRevision
from .locations import StrictModel
from .models import (
    ArtifactRef,
    AssetNode,
    CanonicalKnowledgeSnapshot,
    ChartNode,
    DomainRecord,
    DomainSchemaRef,
    Entity,
    Evidence,
    KnowledgeRevision,
    Relation,
    SchemaEntity,
    SourceVersion,
    StructuralNode,
    TableNode,
    TextBlock,
)


class OutputGap(StrictModel):
    code: str
    detail: str
    object_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class OutputAsset(StrictModel):
    artifact: ArtifactRef
    file: str
    api_path: str


class OutputQuality(StrictModel):
    structural_status: str
    semantic_status: Literal["not_assessed", "needs_enrichment"]
    text_only_complete: bool
    canonical_to_output: Literal["verified"] = "verified"
    source_to_parser: Literal["not_independently_verified"] = "not_independently_verified"
    gaps: list[OutputGap]
    measurements: dict[str, int]


class AIOutput(StrictModel):
    format: Literal["docgrain.ai-document"] = "docgrain.ai-document"
    version: Literal["1.0.0", "1.1.0", "1.2.0"] = "1.0.0"
    document_id: str
    workspace_id: str
    canonical_revision_id: str
    canonical_schema_version: str
    source: SourceVersion
    processing_revision: KnowledgeRevision
    root_node_id: str
    content: list[StructuralNode]
    entities: list[Entity | SchemaEntity]
    relations: list[Relation]
    records: list[DomainRecord]
    domain_schemas: list[DomainSchemaRef]
    evidence: list[Evidence]
    assets: list[OutputAsset]
    metadata: dict[str, JsonValue]
    quality: OutputQuality
    instructions: str = ("Preserve exact cell values, formulas and source evidence. Structural extraction is not "
                         "semantic verification. Undescribed image/chart content is unavailable to a text-only "
                         "model; attach its binary to a multimodal model. Unreviewed entities are proposals. "
                         "Do not infer missing values or treat parser coverage as proof of source completeness.")


    @model_validator(mode="after")
    def versioned_locations(self):
        if self.version == "1.0.0" and any(e.locator.kind == "image_region" for e in self.evidence):
            raise ValueError("standalone image evidence requires AI output 1.1.0")
        if self.version != "1.2.0" and self.canonical_schema_version == "0.6.0":
            raise ValueError("native source facts require AI output 1.2.0")
        return self


class OutputFile(StrictModel):
    name: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    mime_type: str
    storage_uri: str


class OutputPublication(StrictModel):
    version: Literal["1.0.0"] = "1.0.0"
    revision: DerivedRevision
    files: list[OutputFile]


MIME = {"canonical.json":"application/json", "ai.json":"application/json",
        "ai.schema.json":"application/schema+json", "canonical.md":"text/markdown",
        "chunks.jsonl":"application/x-ndjson", "manifest.json":"application/json"}


def project_ai(snapshot: CanonicalKnowledgeSnapshot, chunks: ChunkSet) -> AIOutput:
    snapshot = CanonicalKnowledgeSnapshot.model_validate(snapshot.model_dump(mode="json"))
    by_id = {n.id: n for n in snapshot.structure}
    ordered = []
    def walk(key):
        node = by_id[key]
        ordered.append(node.model_copy(deep=True))
        for child in getattr(node, "children", []):
            walk(child)
    walk(snapshot.root_node_id)
    if {n.id for n in ordered} != set(by_id):
        raise ValueError("output cannot silently omit unreachable canonical nodes")
    gaps = []
    structural = snapshot.metadata.get("structural_parse", {})
    status = structural.get("coverage", {}).get("status", snapshot.knowledge_revision.coverage or "unknown")
    for issue in structural.get("issues", []):
        gaps.append(OutputGap(code="parser_issue", detail=json.dumps(issue, ensure_ascii=False, sort_keys=True)))
    for node in ordered:
        reviews = snapshot.metadata.get("visual_review", {})
        review = reviews.get(node.id, {}) if isinstance(reviews, dict) else {}
        uncertainties = review.get("uncertainties", []) if isinstance(review, dict) else []
        if isinstance(node, (AssetNode, ChartNode)) and isinstance(uncertainties, list):
            for uncertainty in uncertainties:
                if isinstance(uncertainty, str) and uncertainty.strip():
                    gaps.append(OutputGap(code="visual_uncertainty", detail=uncertainty, object_id=node.id,
                                          evidence_ids=node.annotation.provenance.evidence_ids))
        if isinstance(node, (AssetNode, ChartNode)) and not node.description:
            gaps.append(OutputGap(code="missing_visual_description", detail="Binary/visual structure is preserved; visual meaning is not described.",
                                  object_id=node.id, evidence_ids=node.annotation.provenance.evidence_ids))
        if isinstance(node, TableNode):
            for row in node.rows:
                for cell in row:
                    if cell.formula and cell.cached_value is None:
                        gaps.append(OutputGap(code="formula_result_unavailable", detail=f"Formula was preserved without evaluation: {cell.formula}",
                            object_id=node.id, evidence_ids=cell.annotation.provenance.evidence_ids if cell.annotation else []))
    chars = sum(len(n.text) for n in ordered if isinstance(n, TextBlock))
    cells = sum(sum(len(row) for row in n.rows) for n in ordered if isinstance(n, TableNode))
    if not chars and not cells:
        gaps.append(OutputGap(code="no_text_or_table_content", detail="No extracted text/table facts; source may need OCR/visual review."))
    if status != "complete":
        gaps.append(OutputGap(code="structural_coverage_incomplete", detail=f"Structural status: {status}"))
    assets = []
    for artifact in snapshot.artifacts:
        extension = {"image/png":"png", "image/jpeg":"jpg", "image/webp":"webp", "image/gif":"gif"}.get(artifact.mime_type,"bin")
        assets.append(OutputAsset(artifact=artifact,
            file=f"assets/{artifact.content_sha256}.{extension}",
            api_path=f"/v1/knowledge/revisions/{snapshot.knowledge_revision.id}/artifacts/{artifact.id}"))
    quality = OutputQuality(structural_status=status,
        semantic_status="needs_enrichment" if gaps else "not_assessed", text_only_complete=not gaps,
        gaps=gaps, measurements={"nodes":len(ordered), "text_characters":chars, "table_cells":cells,
            "tables":sum(isinstance(n,TableNode) for n in ordered),
            "visual_nodes":sum(isinstance(n,(AssetNode,ChartNode)) for n in ordered),
            "evidence":len(snapshot.evidence), "chunks":len(chunks.chunks),
            "chunk_omissions":len(chunks.chunk_omissions)})
    return AIOutput(version={"0.6.0":"1.2.0", "0.5.0":"1.1.0"}.get(snapshot.schema_version, "1.0.0"),
        document_id=snapshot.document_id, workspace_id=snapshot.workspace_id,
        canonical_revision_id=snapshot.knowledge_revision.id, canonical_schema_version=snapshot.schema_version,
        source=snapshot.source_version, processing_revision=snapshot.knowledge_revision,
        domain_schemas=snapshot.domain_schemas, root_node_id=snapshot.root_node_id, content=ordered,
        entities=snapshot.entities,relations=snapshot.relations,records=snapshot.records,
        evidence=snapshot.evidence,assets=assets,metadata=snapshot.metadata,quality=quality)


def readable(output: AIOutput) -> str:
    """Readable projection; table JSON preserves non-text types, formula/cache and merged spans."""
    lines = ["# " + output.source.filename,
             "\nStructural extraction; semantic content has not been independently verified.\n"]
    for node in output.content:
        lines.append(f"\n<!-- object:{node.id}; evidence:{','.join(node.annotation.provenance.evidence_ids)} -->")
        if node.kind == "section":
            lines.append("#" * min(node.level+1, 6) + " " + node.heading)
        elif isinstance(node,TextBlock):
            lines.append(node.text)
        elif isinstance(node,TableNode):
            lines.append("## " + (node.caption or "Table"))
            lines.append("```json\n" + json.dumps([[cell.model_dump(mode="json") for cell in row] for row in node.rows],
                                                  ensure_ascii=False, indent=2) + "\n```")
        elif isinstance(node,(AssetNode,ChartNode)):
            if isinstance(node, ChartNode) and node.source_data:
                lines.append("## Native chart data (source facts; rendering/visual meaning not verified)\n```json\n" + json.dumps(node.source_data, ensure_ascii=False, indent=2) + "\n```")
            lines.append(node.description or "[Visual content requires image interpretation; see ai.json assets and source evidence.]")
    if output.entities or output.relations or output.records:
        lines.append("\n## Structured records (respect review/validation state)\n```json\n" + json.dumps(
            {key:output.model_dump(mode="json")[key] for key in ("entities","relations","records")},
            ensure_ascii=False,indent=2) + "\n```")
    lines.append("\n## Coverage and unresolved content\n```json\n" + output.quality.model_dump_json(indent=2) + "\n```")
    return "\n\n".join(lines) + "\n"


def output_schema(version: str = "1.0.0") -> dict:
    from .schema import without_image_locations, without_native_facts

    if version not in {"1.0.0", "1.1.0", "1.2.0"}:
        raise ValueError("unsupported AI document version")
    schema = AIOutput.model_json_schema()
    if version != "1.2.0":
        without_native_facts(schema)
        schema["$defs"]["ProcessingSpec"]["properties"]["schema_version"]["enum"].remove("0.6.0")
    if version == "1.0.0":
        without_image_locations(schema)
        schema["$defs"]["ProcessingSpec"]["properties"]["schema_version"]["enum"].remove("0.5.0")
    schema["properties"]["version"].pop("enum")
    schema["properties"]["version"]["const"] = version
    schema["properties"]["version"]["default"] = version
    return schema


def output_bundle(snapshot: CanonicalKnowledgeSnapshot):
    # JSONB can reorder dictionaries. Normalize nested JSON values before any readable
    # string serialization so a freshly mapped revision and its stored replay agree.
    snapshot = CanonicalKnowledgeSnapshot.model_validate(json.loads(canonical_json_bytes(snapshot.model_dump(mode="json"))))
    chunks = derive_chunk_set(snapshot, ChunkingSpec())
    output = project_ai(snapshot, chunks)
    revision = DerivedRevision.create(workspace_id=snapshot.workspace_id,document_id=snapshot.document_id,
        processing_revision_id=snapshot.knowledge_revision.id,stage="projection",
        upstream_revision_ids=(snapshot.knowledge_revision.id,),strategy="ai-document",strategy_version=output.version,
        configuration={"chunking":ChunkingSpec().model_dump(mode="json")})
    files = {"canonical.json":canonical_json_bytes(snapshot.model_dump(mode="json")),
             "ai.json":canonical_json_bytes(output.model_dump(mode="json")),
             "ai.schema.json":canonical_json_bytes(output_schema(output.version)),
             "canonical.md":readable(output).encode(),
             "chunks.jsonl":b"".join(canonical_json_bytes(c.model_dump(mode="json"))+b"\n" for c in chunks.chunks)}
    manifest = {"format":"docgrain.output-manifest", "version":"1.0.0", "revision":revision.model_dump(mode="json"),
        "canonical_sha256":sha256(files["canonical.json"]).hexdigest(),
        "quality":output.quality.model_dump(mode="json"), "chunk_revision":chunks.revision.model_dump(mode="json"),
        "chunk_omissions":[o.model_dump(mode="json") for o in chunks.chunk_omissions],
        "assets":[a.model_dump(mode="json") for a in output.assets],
        "files":[{"name":name,"sha256":sha256(data).hexdigest(),"byte_size":len(data),"mime_type":MIME[name]}
                 for name,data in files.items()]}
    files["manifest.json"] = canonical_json_bytes(manifest)
    return output, chunks, revision, files
