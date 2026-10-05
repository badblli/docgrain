"""Pure manual source-review revisions: typed previews and deterministic child revisions.

No provider, embedding, storage or database access happens here. A review edits only
whitelisted source-checked scalar fields; source, evidence and artifact data are copied
exactly, and the parent's coverage/validation status is never upgraded.
"""

from __future__ import annotations

import json
import re
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
    visual_uncertainties: list[StrictStr] | None = Field(default=None, max_length=20)
    source_evidence_ids: list[StrictStr] = Field(default_factory=list, max_length=20)

    @field_validator("source_evidence_ids")
    @classmethod
    def unique_source_ids(cls, value):
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("source evidence ids must be nonblank and unique")
        return value

    @field_validator("visual_uncertainties")
    @classmethod
    def bounded_uncertainties(cls, value):
        if value is not None and any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("visual uncertainties must be nonblank and bounded")
        return value

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
    visual_uncertainties: list[str] | None = None


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


_AFFECTED_REASON = (
    "Bu alan ilişkili bilgi kayıtlarının dayandığı kaynak kanıtıyla kesişiyor; bağlı "
    "bilgiler yeniden doğrulanana kadar düzenlenemez"
)
_UNKNOWN_REASON = (
    "Bu revision ilişkili bilgi kayıtları içeriyor; bağlı bilgilerin kaynak bağımlılığı "
    "belirlenemediği için hiçbir alan düzenlenemez"
)
# Coarse containers separate pages/sheets/parts. Within a container only supported
# text spans, cell ranges and part paths prove disjointness; PDF pages stay conservative.
_CONTAINER_KEYS = ("page", "page_number", "page_index", "sheet", "sheet_name", "sheet_id",
                   "slide", "slide_number", "part", "part_name", "member")
_PATH_KEYS = ("path", "xpath", "json_pointer", "pointer")


def _containers(locator: dict) -> dict:
    if locator.get("kind") == "text_span":
        return {"source_text": True}
    return {k: locator[k] for k in (*_CONTAINER_KEYS, *_PATH_KEYS)
            if k in locator and locator[k] is not None}


def _locators_relate(left: dict, right: dict) -> str:
    """'disjoint' only when containers demonstrably differ; else 'overlap' or 'ambiguous'."""
    if left == right:
        return "overlap"
    if left.get("kind") != right.get("kind"):
        return "ambiguous"
    kind = left.get("kind")
    if kind == "text_span":
        return "overlap" if max(left["start"], right["start"]) < min(left["end"], right["end"]) else "disjoint"
    if kind == "spreadsheet_range":
        if left["sheet"] != right["sheet"]:
            return "disjoint"

        def bounds(value):
            first, last = (value.split(":") + [value])[:2] if ":" in value else (value, value)
            def point(cell):
                match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", cell)
                if match is None:
                    raise ValueError("Invalid A1 range")
                column = 0
                for letter in match[1]:
                    column = column * 26 + ord(letter) - ord("A") + 1
                return column, int(match[2])
            return (*point(first), *point(last))

        ax, ay, bx, by = bounds(left["a1_range"])
        cx, cy, dx, dy = bounds(right["a1_range"])
        return "disjoint" if bx < cx or dx < ax or by < cy or dy < ay else "overlap"
    a, b = _containers(left), _containers(right)
    if not a or set(a) != set(b):
        return "ambiguous"
    for key in a:
        if a[key] == b[key]:
            continue
        if key in _PATH_KEYS:
            x, y = str(a[key]), str(b[key])
            if x.startswith(y.rstrip("/") + "/") or y.startswith(x.rstrip("/") + "/"):
                continue
        return "disjoint"
    return "overlap"


def _source_refs(value: object, found: list | None = None) -> list | None:
    """Collects explicit 'source_refs' strings; None if one is malformed."""
    found = [] if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "source_refs":
                refs = [item] if isinstance(item, str) else item
                if not isinstance(refs, list) or not all(isinstance(r, str) and r for r in refs):
                    return None
                found.extend(refs)
            elif _source_refs(item, found) is None:
                return None
    elif isinstance(value, list):
        for item in value:
            if _source_refs(item, found) is None:
                return None
    return found


def _linked_dependencies(snapshot: CanonicalKnowledgeSnapshot):
    """(evidence_ids, node_ids) per linked record, or None when any dependency is unknown."""
    evidence = {e.id for e in snapshot.evidence}
    nodes = {n.id: n for n in snapshot.structure}
    entity_ids = {e.id for e in snapshot.entities}
    own: dict[str, set[str]] = {}
    own_nodes: dict[str, set[str]] = {}
    items = [*snapshot.entities, *snapshot.relations, *snapshot.records]
    for item in items:
        annotations = [item.annotation, *item.field_annotations.values()]
        ids = {i for a in annotations for i in a.provenance.evidence_ids}
        if not ids or any(not a.provenance.evidence_ids for a in annotations):
            return None
        refs: list = []
        for payload in (getattr(item, name, None) for name in ("properties", "values", "data")):
            if _source_refs(payload, refs) is None:
                return None
        node_refs = set()
        for ref in refs:
            if ref in evidence:
                ids.add(ref)
            elif ref in nodes:
                # A document/section/list dependency includes its descendants.
                pending = [ref]
                while pending:
                    current = pending.pop()
                    if current in node_refs:
                        continue
                    node_refs.add(current)
                    pending.extend(getattr(nodes[current], "children", []))
            else:
                return None
        if not ids <= evidence:
            return None
        own[item.id] = ids
        own_nodes[item.id] = node_refs
    result = []
    for item in items:
        deps = set(own[item.id])
        dep_nodes = set(own_nodes[item.id])
        if hasattr(item, "from_entity_id"):
            referenced = [item.from_entity_id, item.to_entity_id]
        else:
            referenced = list(getattr(item, "entity_ids", []))
        for entity_id in referenced:
            if entity_id not in entity_ids or entity_id not in own:
                return None
            deps |= own[entity_id]
            dep_nodes |= own_nodes[entity_id]
        result.append((deps, dep_nodes))
    return result


def _dependency_status(snapshot: CanonicalKnowledgeSnapshot, fields: list[ReviewField]) -> list[str]:
    """'free' | 'affected' | 'all' per field (any 'all' blocks every field)."""
    deps = _linked_dependencies(snapshot)
    if deps is None:
        return ["all"] * len(fields)
    locators = {e.id: e.locator.model_dump(mode="json") for e in snapshot.evidence}
    linked_ids = set().union(*(d for d, _ in deps))
    if any(not _containers(locators[i]) for i in linked_ids):
        return ["all"] * len(fields)  # source-wide evidence cannot demonstrate independence
    statuses = []
    for field in fields:
        if not field.evidence_ids:
            statuses.append("affected")
            continue
        if any(i not in locators or not _containers(locators[i]) for i in field.evidence_ids):
            return ["all"] * len(fields)
        status = "free"
        for dep_ids, dep_nodes in deps:
            if field.node_id in dep_nodes or dep_ids & set(field.evidence_ids):
                status = "affected"
                continue
            for mine in field.evidence_ids:
                for theirs in dep_ids:
                    relation = _locators_relate(locators[mine], locators[theirs])
                    if relation == "ambiguous":
                        return ["all"] * len(fields)
                    if relation == "overlap":
                        status = "affected"
        statuses.append(status)
    return statuses


def _targets(snapshot: CanonicalKnowledgeSnapshot) -> list[_Target]:
    targets = _own_targets(snapshot)
    if not (snapshot.entities or snapshot.relations or snapshot.records):
        return targets
    statuses = _dependency_status(snapshot, [t.field for t in targets])
    if "all" in statuses:
        statuses = ["all"] * len(statuses)
    resolved = []
    for target, status in zip(targets, statuses):
        if status != "free":
            reason = _UNKNOWN_REASON if status == "all" else _AFFECTED_REASON
            field = target.field.model_copy(update={"editable": False, "blocked_reason": reason})
            target = _Target(field, target.index, target.raw, target.row, target.col)
        resolved.append(target)
    return resolved


def _own_targets(snapshot: CanonicalKnowledgeSnapshot) -> list[_Target]:
    revision_id = snapshot.knowledge_revision.id

    def build(node, kind, label, raw, evidence, reason, *position, index, row=None, col=None):
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
        if node.kind in {"text_block", "section"}:
            name = "heading" if node.kind == "section" else "text"
            text = node.heading if name == "heading" else node.text
            evidence = _evidence(node.field_annotations.get(f"/{name}")) or _evidence(node.annotation)
            reason = None
            if long_value(text):
                reason = f"Metin {MAX_VALUE_CHARS} karakterlik düzenleme sınırını aşıyor"
            elif not evidence:
                reason = "Bu metnin kaynak konumu kaydedilmemiş"
            targets.append(build(node, "text", f"{'Başlık' if name == 'heading' else 'Metin'}: {_snippet(text)}", text,
                                 evidence, reason, name, index=index))
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
    for change in value["changes"]:
        if change.get("visual_uncertainties") is None:
            change.pop("visual_uncertainties", None)
        if not change.get("source_evidence_ids"):
            change.pop("source_evidence_ids", None)
        else:
            change["source_evidence_ids"].sort()
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
                visual_uncertainties=change.visual_uncertainties,
                source_evidence_ids=change.source_evidence_ids,
            )
        if not _same(change.before, target.raw):
            raise ValueError("review before value is stale for this source revision")
        _check_after(target.field, target.raw, change.after)
        if change.visual_uncertainties is not None and target.field.kind != "description":
            raise ValueError("visual uncertainties require a description field")
        if change.source_evidence_ids and target.field.kind != "description":
            raise ValueError("supplemental source evidence requires a visual field")
        own_source_ids = {e.id for e in snapshot.evidence if e.source_version_id == snapshot.source_version.id}
        if not set(change.source_evidence_ids) <= own_source_ids:
            raise ValueError("unknown or foreign supplemental source evidence")
        visual_reviews = snapshot.metadata.get("visual_review", {})
        visual_review = visual_reviews.get(target.field.node_id, {}) if isinstance(visual_reviews, dict) else {}
        old_uncertainties = visual_review.get("uncertainties", []) if isinstance(visual_review, dict) else []
        uncertainty_changed = change.visual_uncertainties is not None and change.visual_uncertainties != old_uncertainties
        if _same(change.after, change.before) and not uncertainty_changed:
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
                   evidence_ids=sorted(set(t.field.evidence_ids) | set(c.source_evidence_ids)) if c.source_evidence_ids else t.field.evidence_ids,
                   visual_uncertainties=c.visual_uncertainties)
        for t, c in selected
    ]
    request_sha = digest(_normalized(clean))
    proposal_id = "review_proposal_" + digest(
        [revision_id, snapshot_sha, request_sha, [
            d.model_dump(mode="json", exclude={"visual_uncertainties"} if d.visual_uncertainties is None else set())
            for d in diffs]]
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
        source_ids = sorted(set(field.evidence_ids) | set(change.source_evidence_ids)) if change.source_evidence_ids else field.evidence_ids
        annotation = _manual_annotation(producer_id, source_ids, derivation)
        event = {
            "field_id": field.field_id,
            "node_id": field.node_id,
            "kind": field.kind,
            "label": field.label,
            "before": change.before,
            "after": change.after,
            "evidence_ids": list(source_ids),
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
            name = ("heading" if node["kind"] == "section" else "text") if field.kind == "text" else field.kind
            pointer = f"/{name}"
            event["previous_annotation"] = deepcopy(node["annotation"])
            event["previous_field_annotation"] = deepcopy(node["field_annotations"].get(pointer))
            node[name] = change.after
            node["annotation"] = annotation
            node["field_annotations"][pointer] = deepcopy(annotation)
        events.append(event)
        if change.source_evidence_ids:
            event["supplemental_evidence_ids"] = sorted(change.source_evidence_ids)
        if field.kind == "description" and change.visual_uncertainties is not None:
            reviews = data["metadata"].get("visual_review")
            if not isinstance(reviews, dict):
                reviews = {}
                data["metadata"]["visual_review"] = reviews
            event["previous_visual_review"] = deepcopy(reviews.get(field.node_id))
            reviews[field.node_id] = {
                "uncertainties": list(change.visual_uncertainties),
                "reviewer_id": clean.reviewer_id,
                "reviewed_description": change.after,
                "semantic_status": "partial" if change.visual_uncertainties else "description_checked",
            }
            event["visual_uncertainties"] = list(change.visual_uncertainties)

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
