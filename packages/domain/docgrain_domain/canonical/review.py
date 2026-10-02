"""Pure manual source-review revisions: typed previews and deterministic child revisions.

No provider, embedding, storage or database access happens here. A review edits only
whitelisted source-checked scalar fields; source, evidence and artifact data are copied
exactly, and the parent's coverage/validation status is never upgraded.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Literal

from pydantic import (
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)

from .lifecycle import ProcessingSpec, digest, processing_revision_id, scoped_id
from .locations import StrictModel
from .models import Annotation, CanonicalKnowledgeSnapshot

__all__ = [
    "ReviewChange",
    "ReviewDiff",
    "ReviewField",
    "ReviewPreview",
    "ReviewRequest",
    "SaveReviewRequest",
    "build_review_revision",
    "preview_review",
    "review_fields",
]

MAX_VALUE_CHARS = 100_000
MAX_TOTAL_CHARS = 200_000
CONTRACT_VERSION = "review-1"
_OPERATION = "manual-review-1"
_COVERED_KEYS = {"covered", "is_covered", "merged_covered", "covered_by_merge", "merge_covered"}
_COVERED_STATES = {"covered", "covered_by_merge", "hidden", "child"}
_MERGE_KEYS = {"merge", "merged", "merge_state", "merge_role", "merged_cell"}

Scalar = StrictStr | StrictInt | StrictFloat | StrictBool | None
ReviewKind = Literal["text", "table_cell", "description"]


def _finite(value: object) -> object:
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("review values must be finite")
    return value


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must be nonblank")
    return value


class ReviewChange(StrictModel):
    field_id: str = Field(min_length=1)
    before: Scalar
    after: Scalar

    @field_validator("before", "after")
    @classmethod
    def finite(cls, value: object) -> object:
        return _finite(value)


class ReviewRequest(StrictModel):
    base_revision_id: str = Field(min_length=1)
    base_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation_id: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    reviewer_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    changes: list[ReviewChange] = Field(min_length=1, max_length=500)

    @field_validator("operation_id", "reviewer_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("occurred_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value


class SaveReviewRequest(ReviewRequest):
    preview_id: str = Field(min_length=1)
    confirmed_source: Literal[True]

    @field_validator("confirmed_source", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("explicit source confirmation must be true")
        return value


class ReviewField(StrictModel):
    field_id: str
    node_id: str
    kind: ReviewKind
    label: str
    value: Scalar
    evidence_ids: list[str]
    editable: bool
    blocked_reason: str | None = None


class ReviewDiff(StrictModel):
    field_id: str
    node_id: str
    kind: ReviewKind
    label: str
    before: Scalar
    after: Scalar
    evidence_ids: list[str]


class ReviewPreview(StrictModel):
    proposal_id: str
    base_revision_id: str
    snapshot_sha256: str
    review_status: Literal["proposed"] = "proposed"
    changes: list[ReviewDiff]
    warnings: list[str]


@dataclass(frozen=True)
class _Target:
    field: ReviewField
    index: int
    raw: object
    row: int | None = None
    col: int | None = None


def _validated(snapshot: CanonicalKnowledgeSnapshot) -> CanonicalKnowledgeSnapshot:
    # Rejects invalid model_copy mutations at the boundary.
    return CanonicalKnowledgeSnapshot.model_validate(snapshot.model_dump(mode="json"))


def _is_scalar(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and isfinite(value)


def _display(value: object) -> object:
    if _is_scalar(value):
        return value
    if isinstance(value, float):
        return str(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _same(left: object, right: object) -> bool:
    # bool/int/float compare equal in Python; review requires exact type and value.
    return type(left) is type(right) and left == right


def _evidence(annotation: Annotation | None) -> list[str]:
    return list(annotation.provenance.evidence_ids) if annotation is not None else []


def _covered(attributes: object) -> bool:
    """Upstream merge markers for a cell hidden under another cell's merge."""
    if not isinstance(attributes, dict):
        return False
    for key, value in attributes.items():
        name = str(key).lower()
        if name in _COVERED_KEYS and value is True:
            return True
        if name in _MERGE_KEYS:
            if isinstance(value, str) and value.lower() in _COVERED_STATES:
                return True
            if isinstance(value, dict) and _covered(value):
                return True
    return False


def _snippet(value: str) -> str:
    text = " ".join(value.split())
    return text[:48] + ("…" if len(text) > 48 else "")


def _targets(snapshot: CanonicalKnowledgeSnapshot) -> list[_Target]:
    revision_id = snapshot.knowledge_revision.id
    linked = bool(snapshot.entities or snapshot.relations or snapshot.records)
    linked_reason = (
        "Bu revision ilişkili bilgi kayıtları içeriyor; bağlı bilgilerin doğruluğu "
        "henüz alan düzenlemesiyle yeniden doğrulanamıyor"
    )

    def build(node, kind, label, raw, evidence, reason, *position, index, row=None, col=None):
        reason = linked_reason if linked else reason
        field = ReviewField(
            field_id="review_field_" + digest([revision_id, node.id, kind, *position])[:32],
            node_id=node.id,
            kind=kind,
            label=label,
            value=_display(raw),
            evidence_ids=evidence,
            editable=reason is None,
            blocked_reason=reason,
        )
        return _Target(field, index, raw, row, col)

    def long_value(raw: object) -> bool:
        return isinstance(raw, str) and len(raw) > MAX_VALUE_CHARS

    targets: list[_Target] = []
    for index, node in enumerate(snapshot.structure):
        if node.kind == "text_block":
            evidence = _evidence(node.field_annotations.get("/text")) or _evidence(node.annotation)
            reason = None
            if long_value(node.text):
                reason = f"Metin {MAX_VALUE_CHARS} karakterlik düzenleme sınırını aşıyor"
            elif not evidence:
                reason = "Bu metnin kaynak konumu kaydedilmemiş"
            targets.append(build(node, "text", f"Metin: {_snippet(node.text)}", node.text,
                                 evidence, reason, "text", index=index))
        elif node.kind in {"asset", "chart"}:
            evidence = (_evidence(node.field_annotations.get("/description"))
                        or _evidence(node.annotation))
            reason = None
            if long_value(node.description):
                reason = f"Açıklama {MAX_VALUE_CHARS} karakterlik düzenleme sınırını aşıyor"
            elif not evidence:
                reason = "Bu görselin kaynak konumu kaydedilmemiş"
            targets.append(build(node, "description", "Grafik açıklaması" if node.kind == "chart" else "Görsel açıklaması", node.description,
                                 evidence, reason, "description", index=index))
        elif node.kind == "table":
            covered = set()
            for r, row in enumerate(node.rows):
                for c, cell in enumerate(row):
                    for rr in range(r, min(len(node.rows), r + cell.row_span)):
                        for cc in range(c, min(len(node.rows[rr]), c + cell.col_span)):
                            if (rr, cc) != (r, c):
                                covered.add((rr, cc))
            for r, row in enumerate(node.rows):
                for c, cell in enumerate(row):
                    evidence = _evidence(cell.annotation) or _evidence(node.annotation)
                    reason = None
                    if cell.formula is not None or cell.cached_value is not None:
                        reason = "Formül ve hesaplanmış sonuç kaynak dosyasına aittir; burada düzenlenemez"
                    elif (r, c) in covered or _covered(cell.source_attributes):
                        reason = "Birleşik hücrenin altında kalan alanın bağımsız bir kaynak değeri yok"
                    elif not _is_scalar(cell.value):
                        reason = "Liste veya nesne içeren hücreler yalnızca okunabilir"
                    elif long_value(cell.value):
                        reason = f"Hücre {MAX_VALUE_CHARS} karakterlik düzenleme sınırını aşıyor"
                    elif not evidence:
                        reason = "Bu hücrenin kaynak konumu kaydedilmemiş"
                    targets.append(build(node, "table_cell", f"Hücre · satır {r + 1}, sütun {c + 1}",
                                         cell.value, evidence, reason, "cell", r, c,
                                         index=index, row=r, col=c))
    return targets


def review_fields(snapshot: CanonicalKnowledgeSnapshot) -> list[ReviewField]:
    return [target.field for target in _targets(_validated(snapshot))]


def _normalized(request: ReviewRequest) -> dict:
    value = request.model_dump(mode="json", exclude={"preview_id", "confirmed_source"})
    value["changes"] = sorted(value["changes"], key=lambda change: change["field_id"])
    return value


def _check_after(field: ReviewField, before: object, after: object) -> None:
    if isinstance(after, str) and len(after) > MAX_VALUE_CHARS:
        raise ValueError(f"review value exceeds {MAX_VALUE_CHARS} characters")
    if field.kind == "text":
        allowed = isinstance(after, str)
    elif field.kind == "description":
        allowed = after is None or isinstance(after, str)
    else:
        allowed = before is None or type(after) is type(before)
    if not allowed:
        raise ValueError(f"review value type is not allowed for {field.kind} fields")


def _plan(snapshot: CanonicalKnowledgeSnapshot, request: ReviewRequest):
    snapshot = _validated(snapshot)
    clean = ReviewRequest.model_validate(
        request.model_dump(exclude={"preview_id", "confirmed_source"})
    )
    revision_id = snapshot.knowledge_revision.id
    snapshot_sha = digest(snapshot.model_dump(mode="json"))
    if clean.base_revision_id != revision_id or clean.base_snapshot_sha256 != snapshot_sha:
        raise ValueError("review base belongs to another source or processing revision")
    by_id = {target.field.field_id: target for target in _targets(snapshot)}
    chosen: dict[str, tuple[_Target, ReviewChange]] = {}
    total = 0
    for change in clean.changes:
        if change.field_id in chosen:
            raise ValueError("duplicate review field in source revision")
        target = by_id.get(change.field_id)
        if target is None:
            raise ValueError("unknown review field for this source revision")
        if not target.field.editable:
            raise ValueError(f"review field is read-only: {target.field.blocked_reason}")
        # JSON clients serialize 1.0 as 1. Preserve the source's floating type
        # while still rejecting booleans, strings and fractional integer edits.
        if type(target.raw) is float:
            change = ReviewChange(
                field_id=change.field_id,
                before=float(change.before) if type(change.before) is int else change.before,
                after=float(change.after) if type(change.after) is int else change.after,
            )
        if not _same(change.before, target.raw):
            raise ValueError("review before value is stale for this source revision")
        _check_after(target.field, target.raw, change.after)
        if _same(change.after, change.before):
            raise ValueError("review change does not alter the source value")
        if isinstance(change.after, str):
            total += len(change.after)
        chosen[change.field_id] = (target, change)
    if total > MAX_TOTAL_CHARS:
        raise ValueError(f"review changes exceed {MAX_TOTAL_CHARS} total characters")
    clean.changes = [change for _, change in chosen.values()]
    selected = [chosen[t.field.field_id] for t in by_id.values() if t.field.field_id in chosen]
    diffs = [
        ReviewDiff(field_id=t.field.field_id, node_id=t.field.node_id, kind=t.field.kind,
                   label=t.field.label, before=c.before, after=c.after,
                   evidence_ids=t.field.evidence_ids)
        for t, c in selected
    ]
    request_sha = digest(_normalized(clean))
    proposal_id = "review_proposal_" + digest(
        [revision_id, snapshot_sha, request_sha, [d.model_dump(mode="json") for d in diffs]]
    )[:32]
    preview = ReviewPreview(
        proposal_id=proposal_id,
        base_revision_id=revision_id,
        snapshot_sha256=snapshot_sha,
        changes=diffs,
        warnings=[
            "Yalnızca değiştirilen alanlar kaynakla kontrol edilmiş sayılır; belgenin bütünü onaylanmaz.",
            "Önizleme kayıt yapmaz. Kaydederken AI çıktısı ve metin parçaları yenilenir; embedding ve indeks üretilmez.",
            "Çıkarım eksikleri ve kısmi kapsam korunur; açıklanmayan görseller hâlâ açıktır.",
        ],
    )
    return snapshot, clean, selected, preview, request_sha


def preview_review(snapshot: CanonicalKnowledgeSnapshot, request: ReviewRequest) -> ReviewPreview:
    return _plan(snapshot, request)[3]


def _manual_annotation(producer_id: str, evidence_ids: list[str], derivation: str) -> dict:
    return {
        "provenance": {
            "method": "manual",
            "derivation": derivation,
            "producer_id": producer_id,
            "evidence_ids": list(evidence_ids),
            "confidence": None,
            "confidence_method": None,
        },
        "review_status": "approved",
    }


def build_review_revision(
    snapshot: CanonicalKnowledgeSnapshot, request: SaveReviewRequest
) -> CanonicalKnowledgeSnapshot:
    save = SaveReviewRequest.model_validate(request.model_dump())
    snapshot, clean, selected, preview, request_sha = _plan(snapshot, save)
    if save.preview_id != preview.proposal_id:
        raise ValueError("preview belongs to another source, revision or request")

    base = snapshot.model_dump(mode="json")
    data = deepcopy(base)
    parent = snapshot.knowledge_revision
    normalized = _normalized(clean)
    spec = None
    if parent.processing is None:
        revision_id = scoped_id("revision", [parent.id, _OPERATION, request_sha])
    else:
        spec = ProcessingSpec.model_validate({
            **parent.processing.model_dump(mode="json"),
            "options": {
                **parent.processing.options,
                "manual_review": {
                    "base_revision_id": parent.id,
                    "contract_version": CONTRACT_VERSION,
                    "request_sha256": request_sha,
                },
            },
        })
        revision_id = processing_revision_id(snapshot.source_version.id, spec)
    producer_id = scoped_id("producer", [revision_id, _OPERATION])
    producers = [dict(p) for p in base["knowledge_revision"]["producers"]]
    if spec is not None:
        for producer in producers:
            producer["configuration_digest"] = spec.digest
    producers.append({
        "id": producer_id,
        "name": "Docgrain source review",
        "version": "1",
        "configuration_digest": spec.digest if spec is not None else None,
    })
    revision = {
        **base["knowledge_revision"],
        "id": revision_id,
        "parent_revision_id": parent.id,
        "created_at": normalized["occurred_at"],
        "producers": producers,
    }
    if spec is not None:
        revision["processing"] = spec.model_dump(mode="json")
    else:
        revision.pop("processing", None)
    data["knowledge_revision"] = revision

    events = []
    for target, change in selected:
        field = target.field
        node = data["structure"][target.index]
        derivation = "visual_description" if field.kind == "description" else "overridden"
        annotation = _manual_annotation(producer_id, field.evidence_ids, derivation)
        event = {
            "field_id": field.field_id,
            "node_id": field.node_id,
            "kind": field.kind,
            "label": field.label,
            "before": change.before,
            "after": change.after,
            "evidence_ids": list(field.evidence_ids),
        }
        if field.kind == "table_cell":
            cell = node["rows"][target.row][target.col]
            event["row"], event["column"] = target.row, target.col
            event["previous_annotation"] = deepcopy(cell.get("annotation"))
            event["previous_display_text"] = cell.get("display_text")
            cell["value"] = change.after
            cell["annotation"] = annotation
            # A stale rendering would misrepresent the reviewed value; the event keeps it.
            cell["display_text"] = None
        else:
            name = "text" if field.kind == "text" else "description"
            pointer = f"/{name}"
            event["previous_annotation"] = deepcopy(node["annotation"])
            event["previous_field_annotation"] = deepcopy(node["field_annotations"].get(pointer))
            node[name] = change.after
            node["annotation"] = annotation
            node["field_annotations"][pointer] = deepcopy(annotation)
        events.append(event)

    data["metadata"]["manual_review"] = {
        "contract_version": CONTRACT_VERSION,
        "operation_id": clean.operation_id,
        "request_sha256": request_sha,
        "reviewer_id": clean.reviewer_id,
        "reason": clean.reason,
        "occurred_at": normalized["occurred_at"],
        "base_revision_id": parent.id,
        "source_sha256": snapshot.source_version.content_sha256,
        "producer_id": producer_id,
        "changes": events,
        "confirmed_source": True,
    }
    result = CanonicalKnowledgeSnapshot.model_validate(data)
    for name in ("source_version", "evidence", "artifacts"):
        original = base[name]
        current = result.model_dump(mode="json")[name]
        if original != current:
            raise RuntimeError(f"manual review altered immutable {name}")
    return result
