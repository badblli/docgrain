"""Structural canonical publication: source reuse, configuration identity, CAS and replay."""

from __future__ import annotations

import importlib.metadata
import platform
from pathlib import Path

from docgrain_api.canonical_repository import CanonicalConflict, CanonicalRepository
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot, SourceVersion
from docgrain_domain.canonical.lifecycle import (
    ProcessingSpec,
    processing_revision_id,
    source_revision_id,
)

from .canonical_mapper import CanonicalMapper
from .structural import StructuralParseResult


def processing_spec(result: StructuralParseResult) -> ProcessingSpec:
    dependencies = {"python": platform.python_version()}
    packages = ["pydantic"]
    if result.parser == "docling":
        packages += ["docling-core", "docling-ibm-models", "torch", "torchvision", "transformers", "pypdfium2", "pillow"]
    if result.source_format.value == "pdf":
        packages += ["pymupdf"]
    if result.source_format.value in {"docx", "xlsx"}:
        packages += ["lxml", "openpyxl", "python-docx"]
    if result.processing_options.get("ocr_profile"):
        packages += ["easyocr", "opencv-python-headless", "numpy", "scikit-image"]
    for package in packages:
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = "unavailable"
    return ProcessingSpec(parser=result.parser, parser_version=result.parser_version,
                          mapper_version="n2-1" if result.processing_options.get("adapter_version") == "n2-1" else "m2a-1",
                          schema_version=result.processing_options.get("canonical_schema_version", "0.3.0"),
                          dependencies=dependencies,
                          options={"source_format": result.source_format.value, **result.processing_options})


def persist_structural(repository: CanonicalRepository, result: StructuralParseResult, source: SourceVersion,
                       *, pdf_path: Path | None = None,
                       spec: ProcessingSpec | None = None,
                       expected_latest_revision_id: str | None = None) -> tuple[CanonicalKnowledgeSnapshot, bool]:
    """Caller captures expected head before parsing; concurrent reprocess never silently wins."""
    spec = spec or processing_spec(result)
    if spec.parser != result.parser or spec.parser_version != result.parser_version:
        raise ValueError("processing spec does not describe the actual parser")
    source_id = source_revision_id(source.workspace_id, source.document_id, source.content_sha256)
    source = source.model_copy(update={"id": source_id})
    stored_source = repository.get_source(source_id)
    if stored_source is not None:
        if (stored_source.document_id, stored_source.workspace_id, stored_source.content_sha256,
                stored_source.byte_size, stored_source.mime_type) != (
                source.document_id, source.workspace_id, source.content_sha256, source.byte_size, source.mime_type):
            raise CanonicalConflict("source content/scope metadata mismatch")
        source = stored_source
    revision_id = processing_revision_id(source_id, spec)
    existing = repository.get_snapshot(revision_id)
    parent = existing.knowledge_revision.parent_revision_id if existing else expected_latest_revision_id
    # Stable source receipt time makes concurrent duplicate publication byte-identical.
    # Repository insertion time separately records actual publication chronology.
    created_at = existing.knowledge_revision.created_at if existing else source.recorded_at
    snapshot = CanonicalMapper().map(result, source, revision_id=revision_id, created_at=created_at,
                                     processing=spec, parent_revision_id=parent, pdf_path=pdf_path)
    inserted = repository.append(snapshot, expected_latest_revision_id=parent)
    return snapshot, inserted
