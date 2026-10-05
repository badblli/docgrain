"""Check golden table cells against canonical table nodes."""

from .golden import TableFact
from .scoring import normalize


def _cell(cell: object) -> str:
    if isinstance(cell, dict):
        value = cell.get("display_text") or cell.get("value")
    else:
        value = cell
    return normalize(value if value is not None else "")


def _locator_matches(node: dict, evidence: dict, fact: TableFact) -> bool:
    locator = evidence.get("locator", {})
    if fact.page is not None and locator.get("page_number") != fact.page:
        return False
    return fact.sheet is None or normalize(locator.get("sheet", "")) == normalize(fact.sheet)


def check_fact(fact: TableFact, snapshot: dict) -> dict:
    evidence = {item["id"]: item for item in snapshot.get("evidence", [])}
    candidates = []
    structure = snapshot.get("structure", [])
    for position, node in enumerate(structure):
        if node.get("kind") != "table":
            continue
        ids = node.get("annotation", {}).get("provenance", {}).get("evidence_ids", [])
        if (fact.page is not None or fact.sheet is not None) and not any(
            item in evidence and _locator_matches(node, evidence[item], fact) for item in ids
        ):
            continue
        if fact.table_hint:
            nearby = [node.get("caption") or ""]
            nearby.extend(
                previous.get("heading") or previous.get("text") or ""
                for previous in structure[max(0, position - 3):position]
                if previous.get("kind") in {"section", "text_block"}
            )
            if not any(normalize(fact.table_hint) in normalize(text) for text in nearby):
                continue
        candidates.append(node)
    for node in candidates:
        rows = node.get("rows", [])
        if not rows:
            continue
        header = [_cell(cell) for cell in rows[0]]
        columns = [index for index, label in enumerate(header)
                   if normalize(fact.column_label) in label]
        for row in rows[1:]:
            if not row or normalize(fact.row_label) not in _cell(row[0]):
                continue
            for index in columns:
                if index < len(row):
                    actual = _cell(row[index])
                    return {"id": fact.id, "status": "found" if actual == normalize(fact.expected)
                            else "wrong", "actual": actual, "table_id": node.get("id")}
    return {"id": fact.id, "status": "missing", "actual": None, "table_id": None}
