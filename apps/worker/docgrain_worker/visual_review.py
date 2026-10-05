"""Reconcile selected table proposals against independently reviewed source cells.

The preview is a review artifact, never a canonical revision or publishable output.
"""

from copy import deepcopy
from hashlib import sha256

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot

from .fidelity import golden_table_checks
from .selective_vision import (
    Observation,
    SelectedRequest,
    prepare_request,
    render_table_page,
)


def review_table_proposal(snapshot: CanonicalKnowledgeSnapshot, proposal: dict,
                         source_bytes: bytes, checks: list[dict]) -> dict:
    request = SelectedRequest.model_validate(proposal["request"])
    if request.task != "table":
        raise ValueError("table review requires a table proposal")
    image = render_table_page(source_bytes, request.input_locator["page_number"])
    pinned = prepare_request(snapshot, request.target_node_id, image, task="table",
                             source_bytes=source_bytes, context=request.context,
                             input_locator=request.input_locator)
    if pinned != request:
        raise ValueError("proposal source/revision/evidence/input binding differs")
    observation = Observation.model_validate(proposal["observation"])
    table = next(node for node in snapshot.structure if node.id == request.target_node_id)
    rows = observation.table_rows
    if len(rows) != len(table.rows) or any(len(a) != len(b) for a, b in zip(rows, table.rows, strict=True)):
        raise ValueError("table shape changes require separate structural review")
    golden = golden_table_checks(snapshot, checks)
    coordinates = {}
    for check in golden:
        if check["node_id"] != table.id or not check["found"]:
            raise ValueError("review assertion does not identify a selected table cell")
        key = (check["row"], check["column"])
        if key in coordinates:
            raise ValueError("duplicate source assertions are ambiguous")
        coordinates[key] = check["expected"]
    preview = [[cell.value for cell in row] for row in table.rows]
    decisions = []
    for row, cells in enumerate(rows):
        for column, proposed in enumerate(cells):
            current = preview[row][column]
            if current == proposed:
                continue
            key = (row, column)
            decision = "needs_source_review"
            if key in coordinates:
                decision = "source_checked" if proposed == coordinates[key] else "rejected"
            if decision == "source_checked":
                preview[row][column] = proposed
            decisions.append({"row": row, "column": column, "before": current,
                              "proposed": proposed, "decision": decision})
    after = deepcopy(golden)
    for check in after:
        check["actual"] = preview[check["row"]][check["column"]]
        check["matches"] = check["actual"] == check["expected"]
    return {"format": "docgrain.table-review", "version": "1.0.0",
            "review_status": "proposed", "request": request.model_dump(mode="json"),
            "source_sha256": sha256(source_bytes).hexdigest(),
            "decisions": decisions, "preview_rows": preview,
            "golden_before": golden, "golden_after": after,
            "limitations": ["Only independently checked cells are changed in this local preview.",
                            "No canonical revision, output package, head or embedding was changed."]}
