"""Docgrain's canonical v0.1 contract, independent of runtime parser and provider types."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, JsonValue, field_validator, model_validator

from .identity import IDENTITY_POLICY_VERSION
from .locations import Locator, StrictModel

ReviewStatus = Literal["unreviewed", "proposed", "approved", "rejected", "overridden"]
ValidationStatus = Literal["not_validated", "valid", "invalid", "unavailable"]
Method = Literal["source", "parser", "vision", "model", "manual"]
Derivation = Literal["direct", "normalized", "visual_description", "inferred", "overridden"]


class SourceVersion(StrictModel):
    """Immutable metadata contract; current overwriteable MinIO uploads are not verified sources."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    storage_uri: str = Field(min_length=1)
    storage_version: str | None = None
    byte_size: int = Field(ge=0)
    mime_type: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        return value


class Producer(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str | None = None
    configuration_digest: str | None = None


class KnowledgeRevision(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    source_version_id: str = Field(min_length=1)
    parent_revision_id: str | None = None
    created_at: datetime
    producers: tuple[Producer, ...] = Field(min_length=1)
    coverage: str | None = None

    @field_validator("created_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class DateRange(StrictModel):
    kind: Literal["date_range"] = "date_range"
    valid_from: date | None = None
    valid_until: date | None = None

    @model_validator(mode="after")
    def check(self) -> DateRange:
        if self.valid_from is None and self.valid_until is None:
            raise ValueError("at least one temporal boundary is required")
        if self.valid_from is not None and self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("temporal range must be increasing")
        return self


class DatetimeRange(StrictModel):
    kind: Literal["datetime_range"] = "datetime_range"
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def check(self) -> DatetimeRange:
        if self.valid_from is None and self.valid_until is None:
            raise ValueError("at least one temporal boundary is required")
        for value in (self.valid_from, self.valid_until):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("datetime boundary must be timezone-aware")
        if self.valid_from is not None and self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("temporal range must be increasing")
        return self


TemporalValidity = Annotated[DateRange | DatetimeRange, Field(discriminator="kind")]


class Provenance(StrictModel):
    method: Method
    derivation: Derivation
    producer_id: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    confidence_method: str | None = None

    @model_validator(mode="after")
    def measured_confidence(self) -> Provenance:
        if self.confidence is not None and not self.confidence_method:
            raise ValueError("confidence_method is required when confidence is measured")
        return self


class Annotation(StrictModel):
    provenance: Provenance
    review_status: ReviewStatus = "unreviewed"


class Evidence(StrictModel):
    id: str = Field(min_length=1)
    source_version_id: str = Field(min_length=1)
    locator: Locator
    note: str | None = None


class ArtifactRef(StrictModel):
    id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    storage_uri: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    mime_type: str = Field(min_length=1)


class DomainSchemaRef(StrictModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dialect: Literal["https://json-schema.org/draft/2020-12/schema"] = (
        "https://json-schema.org/draft/2020-12/schema"
    )


class DomainValidationResult(StrictModel):
    status: ValidationStatus = "not_validated"
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def error_consistency(self) -> DomainValidationResult:
        if self.status == "invalid" and not self.errors:
            raise ValueError("invalid validation requires errors")
        if self.status != "invalid" and self.errors:
            raise ValueError("only invalid validation may carry errors")
        return self


class NodeBase(StrictModel):
    id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    annotation: Annotation
    field_annotations: dict[str, Annotation] = Field(default_factory=dict)


class DocumentNode(NodeBase):
    kind: Literal["document"] = "document"
    title: str | None = None
    children: list[str] = Field(default_factory=list)


class SectionNode(NodeBase):
    kind: Literal["section"] = "section"
    heading: str
    level: int = Field(ge=1)
    children: list[str] = Field(default_factory=list)


class TextBlock(NodeBase):
    kind: Literal["text_block"] = "text_block"
    text: str
    role: Literal["paragraph", "heading", "caption", "other"] = "paragraph"


class TableCell(StrictModel):
    value: JsonValue
    annotation: Annotation | None = None
    # 0.2.0: preserve spreadsheet source facts without evaluating formulas.
    formula: str | None = None
    cached_value: JsonValue = None
    display_text: str | None = None
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)


class TableNode(NodeBase):
    kind: Literal["table"] = "table"
    rows: list[list[TableCell]] = Field(default_factory=list)
    caption: str | None = None


class AssetNode(NodeBase):
    kind: Literal["asset"] = "asset"
    artifact_id: str = Field(min_length=1)
    description: str | None = None


class ChartNode(NodeBase):
    kind: Literal["chart"] = "chart"
    artifact_id: str | None = None
    description: str | None = None


class ListNode(NodeBase):
    kind: Literal["list"] = "list"
    ordered: bool = False
    children: list[str] = Field(default_factory=list)


StructuralNode = Annotated[
    DocumentNode | SectionNode | TextBlock | TableNode | AssetNode | ChartNode | ListNode,
    Field(discriminator="kind"),
]


class Entity(StrictModel):
    id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    type: str = Field(min_length=1)
    label: str
    properties: dict[str, JsonValue] = Field(default_factory=dict)
    annotation: Annotation
    field_annotations: dict[str, Annotation] = Field(default_factory=dict)
    validity: TemporalValidity | None = None


class Relation(StrictModel):
    id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    type: str = Field(min_length=1)
    from_entity_id: str = Field(min_length=1)
    to_entity_id: str = Field(min_length=1)
    properties: dict[str, JsonValue] = Field(default_factory=dict)
    annotation: Annotation
    field_annotations: dict[str, Annotation] = Field(default_factory=dict)
    validity: TemporalValidity | None = None


class DomainRecord(StrictModel):
    id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    schema_id: str = Field(min_length=1)
    values: dict[str, JsonValue]
    annotation: Annotation
    field_annotations: dict[str, Annotation] = Field(default_factory=dict)
    validation: DomainValidationResult = Field(default_factory=DomainValidationResult)
    entity_ids: list[str] = Field(default_factory=list)
    validity: TemporalValidity | None = None

    @model_validator(mode="after")
    def invalid_not_approved(self) -> DomainRecord:
        if self.validation.status == "invalid" and self.annotation.review_status == "approved":
            raise ValueError("invalid domain record cannot be approved")
        return self


class CanonicalKnowledgeSnapshot(StrictModel):
    schema_version: Literal["0.1.0", "0.2.0"] = "0.2.0"
    identity_policy_version: Literal["0.1.0"] = IDENTITY_POLICY_VERSION
    document_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    source_version: SourceVersion
    knowledge_revision: KnowledgeRevision
    root_node_id: str = Field(min_length=1)
    structure: list[StructuralNode] = Field(min_length=1)
    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    records: list[DomainRecord] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    domain_schemas: list[DomainSchemaRef] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def semantic_validation(self) -> CanonicalKnowledgeSnapshot:
        from .validation import validate_snapshot

        if self.schema_version == "0.1.0":
            for node in self.structure:
                if isinstance(node, TableNode):
                    for row in node.rows:
                        for cell in row:
                            if (cell.formula is not None or cell.cached_value is not None
                                    or cell.display_text is not None or cell.row_span != 1 or cell.col_span != 1):
                                raise ValueError("0.2.0 table cell fields require schema_version 0.2.0")
        validate_snapshot(self)
        return self
