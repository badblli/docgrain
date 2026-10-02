"""Revision-pinned visual inventory and non-publishing classification previews.

No classifier, OCR engine or provider is called here. Repeated binaries never
establish that a picture is decorative; human labels remain proposals.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from .identity import canonical_json_bytes
from .lifecycle import digest
from .locations import StrictModel
from .models import CanonicalKnowledgeSnapshot

VisualKind = Literal[
    "unknown", "logo", "decorative", "photo", "table", "plan", "diagram", "chart"
]


class VisualRegion(StrictModel):
    id: str
    node_id: str
    node_kind: Literal["asset", "chart", "table"]
    classification: VisualKind
    classification_method: Literal["unknown", "source_structure"]
    evidence_ids: list[str]
    artifact_id: str | None = None
    binary_sha256: str | None = None
    binary_available: bool
    duplicate_of: str | None = None
    native_chart_data: bool = False
    description_present: bool = False
    source_review_status: str
    actions: list[str]


class VisualInventory(StrictModel):
    format: Literal["docgrain.visual-inventory"] = "docgrain.visual-inventory"
    version: Literal["1.0.0"] = "1.0.0"
    id: str
    workspace_id: str
    document_id: str
    revision_id: str
    source_sha256: str
    snapshot_sha256: str
    regions: list[VisualRegion]
    unresolved_picture_refs: list[str]
    limitations: list[str]


class VisualDecision(StrictModel):
    region_id: str = Field(min_length=1)
    classification: VisualKind
    reviewer_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reviewer_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reviewer and source review reason must be nonblank")
        return value


class VisualPreviewRequest(StrictModel):
    inventory_id: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decisions: list[VisualDecision] = Field(min_length=1, max_length=10000)


class VisualReviewPreview(StrictModel):
    format: Literal["docgrain.visual-review"] = "docgrain.visual-review"
    version: Literal["1.0.0"] = "1.0.0"
    id: str
    review_status: Literal["proposed"] = "proposed"
    inventory: VisualInventory
    decisions: list[VisualDecision]
    limitations: list[str]


def visual_inventory(snapshot: CanonicalKnowledgeSnapshot) -> VisualInventory:
    # Reject invalid model_copy mutations at the boundary, as other projections do.
    snapshot = CanonicalKnowledgeSnapshot.model_validate(
        snapshot.model_dump(mode="json")
    )
    artifact_by_id = {a.id: a for a in snapshot.artifacts}
    seen: dict[str, str] = {}
    regions = []
    for node in snapshot.structure:
        if node.kind not in {"asset", "chart", "table"}:
            continue
        artifact = artifact_by_id.get(getattr(node, "artifact_id", None))
        binary = artifact is not None and artifact.role == "source-image"
        evidence = sorted(
            set(node.annotation.provenance.evidence_ids)
            | {
                eid
                for ann in node.field_annotations.values()
                for eid in ann.provenance.evidence_ids
            }
        )
        actions = []
        if node.kind == "asset":
            actions.append("classify_visual")
        if node.kind == "table":
            actions.append("review_table_source")
        else:
            if not evidence:
                actions.append("missing_source_evidence")
            if (
                binary
                and artifact.mime_type in {"image/png", "image/jpeg"}
                and evidence
            ):
                actions.append("local_ocr_available")
            elif not binary:
                actions.append("no_raster_binary")
            if not getattr(node, "description", None):
                actions.append("visual_meaning_unresolved")
        native = node.kind == "chart" and node.source_data is not None
        if native:
            actions.append("inspect_native_chart_data")
        binary_hash = artifact.content_sha256 if binary else None
        duplicate = seen.get(binary_hash) if binary_hash else None
        if binary_hash:
            seen.setdefault(binary_hash, node.id)
        region = VisualRegion(
            id="visual_region_"
            + digest([snapshot.knowledge_revision.id, node.id, evidence])[:32],
            node_id=node.id,
            node_kind=node.kind,
            classification=node.kind if node.kind in {"table", "chart"} else "unknown",
            classification_method="source_structure"
            if node.kind in {"table", "chart"}
            else "unknown",
            evidence_ids=evidence,
            artifact_id=artifact.id if artifact else None,
            binary_sha256=binary_hash,
            binary_available=binary,
            duplicate_of=duplicate,
            native_chart_data=native,
            description_present=bool(getattr(node, "description", None)),
            source_review_status=node.annotation.review_status,
            actions=actions,
        )
        regions.append(region)
    parse = snapshot.metadata.get("structural_parse")
    issues = parse.get("issues", []) if isinstance(parse, dict) else []
    issues = (
        [issue for issue in issues if isinstance(issue, dict)]
        if isinstance(issues, list)
        else []
    )
    payload = dict(
        workspace_id=snapshot.workspace_id,
        document_id=snapshot.document_id,
        revision_id=snapshot.knowledge_revision.id,
        source_sha256=snapshot.source_version.content_sha256,
        snapshot_sha256=digest(snapshot.model_dump(mode="json")),
        regions=regions,
        unresolved_picture_refs=[
            issue.get("item_ref") or f"unlocated-picture:{i}"
            for i, issue in enumerate(issues)
            if issue.get("code") == "unextracted_picture"
        ],
        limitations=[
            "Binary availability is a recorded artifact reference, not a storage health check.",
            "Duplicate hashes do not establish logo, decoration or semantic equivalence.",
            "OCR capability and descriptions do not certify source meaning or source acceptance.",
            "Inventory is read-only; canonical revisions and published packages are unchanged.",
        ],
    )
    # DTO dump ensures model objects are converted before deterministic hashing.
    value = VisualInventory(id="pending", **payload)
    identity = value.model_dump(mode="json", exclude={"id"})
    return value.model_copy(update={"id": "visual_inventory_" + digest(identity)[:32]})


def preview_visual_review(
    snapshot: CanonicalKnowledgeSnapshot, request: VisualPreviewRequest
) -> VisualReviewPreview:
    inventory = visual_inventory(snapshot)
    if (
        request.inventory_id != inventory.id
        or request.snapshot_sha256 != inventory.snapshot_sha256
    ):
        raise ValueError(
            "visual inventory belongs to another source or processing revision"
        )
    regions = {r.id: r for r in inventory.regions}
    seen = set()
    for decision in request.decisions:
        region = regions.get(decision.region_id)
        if region is None or decision.region_id in seen:
            raise ValueError("unknown or duplicate visual region decision")
        if region.node_kind != "asset" and decision.classification != region.node_kind:
            raise ValueError(
                "native table/chart kind cannot be replaced by a visual label"
            )
        if not region.evidence_ids:
            raise ValueError("classification requires source evidence")
        seen.add(decision.region_id)
    decisions = sorted(request.decisions, key=lambda decision: decision.region_id)
    value = VisualReviewPreview(
        id="pending",
        inventory=inventory,
        decisions=decisions,
        limitations=[
            "Classification is a manual proposal, not an accepted source interpretation.",
            "Logo/decorative proposals do not remove binaries or close quality gaps.",
            "Preview creates no canonical revision, database write, model call or publication.",
        ],
    )
    return value.model_copy(
        update={
            "id": "visual_review_"
            + digest(value.model_dump(mode="json", exclude={"id"}))[:32]
        }
    )


def verify_inventory(
    snapshot: CanonicalKnowledgeSnapshot, inventory: VisualInventory
) -> None:
    if canonical_json_bytes(inventory.model_dump(mode="json")) != canonical_json_bytes(
        visual_inventory(snapshot).model_dump(mode="json")
    ):
        raise ValueError("inventory differs from pinned source/revision")
