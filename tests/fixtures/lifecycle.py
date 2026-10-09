"""Provider-free M2a processing/derived manifest fixtures (no generated chunks/indexes)."""

from datetime import UTC, datetime
from hashlib import sha256

from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.lifecycle import (
    DerivedRevision,
    ProcessingSpec,
    chunk_id,
    processing_revision_id,
    source_revision_id,
)
from docgrain_domain.canonical.lineage import DerivedManifest, LineageEdge, ObjectRef
from docgrain_domain.source_format import IMAGE_FORMATS, SourceFormat
from docgrain_worker.canonical_mapper import CanonicalMapper
from docgrain_worker.structural import StructuralItem, StructuralParseResult


def mapped_snapshot(fmt=SourceFormat.TXT, *, pdf_path=None, mapper_version="m2a-1"):
    locators = {
        SourceFormat.PDF: {"kind": "pdf_raw", "page_number": 1,
                           "bbox": {"l": 60, "t": 160, "r": 260, "b": 100, "coord_origin": "BOTTOMLEFT"}},
        SourceFormat.DOCX: {"kind": "docx_block", "part": "word/document.xml", "path": "/body/p[1]"},
        SourceFormat.TXT: {"kind": "text_span", "start": 0, "end": 5},
        SourceFormat.XLSX: {"kind": "spreadsheet_range", "sheet": "Data", "a1_range": "A1:B2"},
        SourceFormat.PNG: {"kind": "image_region", "width_px": 800, "height_px": 600, "exif_orientation": 1,
                           "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1}},
        SourceFormat.JPEG: {"kind": "image_region", "width_px": 800, "height_px": 600, "exif_orientation": 6,
                            "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1}},
    }
    # WP106: the other Docling formats map to Docling JSON object paths; new image types to image regions.
    image = fmt in IMAGE_FORMATS
    locator = locators.get(fmt) or (locators[SourceFormat.PNG] if image else {"kind": "docx_raw", "ref": "#/texts/0"})
    result = StructuralParseResult(fmt, "test-parser", "1", "complete", [
        StructuralItem("paragraph", "first", locator, text="Hello", page_size=(600, 800))
    ], ["area:1"], ["area:1"], [])
    if locator["kind"] == "docx_raw":
        result.legacy_json = b'{"texts": [{"text": "Hello"}]}'
    content_hash = sha256(fmt.value.encode()).hexdigest()
    source = SourceVersion(id=source_revision_id("workspace-test", "document-test", content_hash),
                           document_id="document-test", workspace_id="workspace-test", content_sha256=content_hash,
                           storage_uri="fixture://original", storage_version="v1", byte_size=5,
                           mime_type="application/test", filename=f"test.{fmt.value}",
                           recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    spec = ProcessingSpec(parser=result.parser, parser_version=result.parser_version,
                          schema_version="0.5.0" if image else "0.3.0",
                          mapper_version=mapper_version)
    snapshot = CanonicalMapper().map(result, source, processing=spec,
                                     revision_id=processing_revision_id(source.id, spec),
                                     created_at=source.recorded_at, pdf_path=pdf_path)
    return snapshot, result, source, spec


def derived_chain(snapshot):
    processing_id = snapshot.knowledge_revision.id
    canonical = ObjectRef(kind="canonical", revision_id=processing_id, object_id=snapshot.structure[-1].id)
    upstream = canonical
    manifests = []
    for stage, kind in (("chunking", "chunk"), ("embedding", "embedding"), ("indexing", "index")):
        revision = DerivedRevision.create(workspace_id=snapshot.workspace_id, document_id=snapshot.document_id,
                                           processing_revision_id=processing_id, stage=stage,
                                           upstream_revision_ids=(upstream.revision_id,),
                                           strategy=f"test-{stage}", strategy_version="1")
        identity = (chunk_id(snapshot.document_id, [canonical.object_id], "test-chunking", "1", 0,
                             sha256(b"Hello").hexdigest()) if kind == "chunk" else f"{kind}-test")
        target = ObjectRef(kind=kind, revision_id=revision.id, object_id=identity)
        manifests.append(DerivedManifest(revision=revision, objects=[target],
                                         edges=[LineageEdge(upstream=upstream, downstream=target)]))
        upstream = target
    return canonical, manifests
