"""Explicit canonical table-to-candidate mapping, independent of business domain."""

from copy import deepcopy
from dataclasses import dataclass

from docgrain_domain.canonical.models import (
    Annotation,
    CanonicalKnowledgeSnapshot,
    Producer,
    TableNode,
)

from .entity_service import EntityCandidate


@dataclass(frozen=True)
class ColumnBinding:
    column: int
    cast: str = "identity"


def table_candidates(snapshot: CanonicalKnowledgeSnapshot, table_id: str, *, bindings: dict[str, ColumnBinding],
                     identity_field: str, entity_type: str, producer: Producer, skip_rows: int = 1) -> list[EntityCandidate]:
    """Caller chooses fields/casts explicitly; no domain guessing or silent conversion."""
    from docgrain_domain.canonical.entity_fields import pointer

    table = next((node for node in snapshot.structure if node.id == table_id), None)
    if not isinstance(table, TableNode) or skip_rows < 0 or identity_field not in bindings:
        raise ValueError("table, nonnegative skip_rows and bound identity field are required")
    candidates = []
    casts = {"identity": lambda value: value, "string": str, "integer": int, "number": float}
    for row in table.rows[skip_rows:]:
        data = {}
        annotations = {}
        evidence = []
        for field, binding in bindings.items():
            if binding.column < 0 or binding.column >= len(row) or binding.cast not in casts:
                raise ValueError("column binding is outside the row or has an unsupported cast")
            cell = row[binding.column]
            if cell.value is None or (binding.cast in {"integer", "number"} and isinstance(cell.value, bool)):
                raise ValueError("missing/boolean cell cannot be silently converted to a field")
            if binding.cast == "integer" and isinstance(cell.value, float) and not cell.value.is_integer():
                raise ValueError("fractional cell cannot be truncated to an integer")
            data[field] = casts[binding.cast](cell.value)
            annotation = deepcopy((cell.annotation or table.annotation).model_dump(mode="json"))
            annotation["review_status"] = "unreviewed"
            annotation["provenance"]["producer_id"] = producer.id
            annotation["provenance"]["derivation"] = "direct" if binding.cast == "identity" else "normalized"
            # Source/parser confidence cannot be copied as a measurement of this transformation.
            annotation["provenance"]["confidence"] = None
            annotation["provenance"]["confidence_method"] = None
            annotations[pointer([field])] = Annotation.model_validate(annotation)
            evidence.extend(annotation["provenance"]["evidence_ids"])
        overall = deepcopy(table.annotation.model_dump(mode="json"))
        overall["provenance"].update(producer_id=producer.id, derivation="normalized",
                                     confidence=None, confidence_method=None, evidence_ids=list(dict.fromkeys(evidence)))
        overall["review_status"] = "proposed"
        key = str(data[identity_field])
        candidates.append(EntityCandidate(identity_key=key, type=entity_type, label=key, data=data,
                                           annotation=Annotation.model_validate(overall), field_annotations=annotations))
    return candidates
