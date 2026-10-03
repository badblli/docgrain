"""Manual review eligibility with linked entities/relations/records: per-field evidence dependency."""

import pytest
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.review import (
    build_review_revision,
    preview_review,
    review_fields,
)

from tests.unit.test_manual_review import legacy, node, node_fields, prepared, request

CONTAINER_KEYS = ("page", "page_number", "page_index", "sheet", "sheet_name", "sheet_id",
                  "slide", "slide_number", "part", "part_name", "member", "path", "xpath")


def ann(evidence_ids, producer_id):
    return {
        "provenance": {"method": "parser", "derivation": "direct", "producer_id": producer_id,
                       "evidence_ids": evidence_ids, "confidence": None},
        "review_status": "unreviewed",
    }


def other_evidence(base):
    """A second evidence item whose locator sits in a different container (page/sheet/part)."""
    first = base.evidence[0].model_dump(mode="json")
    locator = dict(first["locator"])
    keys = [k for k in CONTAINER_KEYS if locator.get(k) is not None]
    assert keys, "fixture locator has no container key; adapt CONTAINER_KEYS"
    for key in keys:
        value = locator[key]
        locator[key] = value + 7 if isinstance(value, int) and not isinstance(value, bool) else f"other:{value}"
    return {**first, "id": "evidence-other-container", "locator": locator}


def linked(mutate=None, *, entity_evidence=None):
    """legacy() plus an independent text node and a linked entity citing evidence[0]."""
    base = legacy()
    producer = base.knowledge_revision.producers[0].id
    ev0 = base.evidence[0].id
    other = other_evidence(base)
    data = base.model_dump(mode="json")
    data["evidence"].append(other)
    indep = node(base, "text_block", "review:indep", text="Independent", role="paragraph",
                 annotation=ann([other["id"]], producer))
    data["structure"].append(indep)
    next(n for n in data["structure"] if n["id"] == data["root_node_id"])["children"].append(indep["id"])
    table = next(n for n in data["structure"] if n["identity_key"] == "review:table")
    for r, c in ((0, 0), (1, 0), (1, 2)):  # cell-level evidence in the other container
        table["rows"][r][c]["annotation"] = ann([other["id"]], producer)
    data["entities"] = [{
        "id": "entity-1", "identity_key": "entity:1", "type": "Thing", "label": "Thing",
        "annotation": ann(entity_evidence if entity_evidence is not None else [ev0], producer),
    }]
    if mutate:
        mutate(data, base)
    return CanonicalKnowledgeSnapshot.model_validate(data)


def test_independent_node_is_editable_and_linked_data_is_preserved_exactly():
    snapshot = linked()
    indep = node_fields(snapshot, "review:indep")[0]
    assert indep.editable
    affected = node_fields(snapshot, "review:text")[0]
    assert not affected.editable and "ilişkili" in affected.blocked_reason
    before = snapshot.model_dump(mode="json")
    result = build_review_revision(snapshot, prepared(snapshot, (indep, "Independent corrected")))
    assert snapshot.model_dump(mode="json") == before
    after = result.model_dump(mode="json")
    for name in ("entities", "relations", "records", "evidence", "artifacts", "domain_schemas"):
        assert after[name] == before[name]
    untouched = [n for n in before["structure"] if n["id"] != indep.node_id]
    assert [n for n in after["structure"] if n["id"] != indep.node_id] == untouched


def test_affected_node_stays_readonly_and_cannot_be_previewed():
    snapshot = linked()
    for key in ("review:text", "review:asset-bare"):
        for field in node_fields(snapshot, key):
            assert not field.editable and field.blocked_reason
    text = node_fields(snapshot, "review:text")[0]
    with pytest.raises(ValueError, match="read-only"):
        preview_review(snapshot, request(snapshot, (text, "changed")))


def test_shared_evidence_blocks_node_and_cell_but_cell_with_own_evidence_is_free():
    snapshot = linked()
    cells = node_fields(snapshot, "review:table")
    # (0,0) cites the other container; (0,1)/(0,2) fall back to the table's evidence[0].
    assert cells[0].editable
    assert not cells[1].editable and not cells[2].editable
    assert cells[1].evidence_ids == [snapshot.evidence[0].id]
    shared = linked(entity_evidence=[snapshot_evidence_id()])
    assert not node_fields(shared, "review:indep")[0].editable  # now shares the indep evidence
    assert node_fields(shared, "review:text")[0].editable  # and evidence[0] is no longer linked


def snapshot_evidence_id():
    return "evidence-other-container"


def test_unknown_dependency_blocks_every_field():
    def no_evidence(data, base):
        data["entities"].append({
            "id": "entity-2", "identity_key": "entity:2", "type": "Thing", "label": "Unknown",
            "annotation": ann([], base.knowledge_revision.producers[0].id),
        })

    snapshot = linked(no_evidence)
    fields = review_fields(snapshot)
    assert fields and not any(f.editable for f in fields)
    assert all("belirlenemediği" in f.blocked_reason for f in fields)
    indep = node_fields(snapshot, "review:indep")[0]
    with pytest.raises(ValueError, match="read-only"):
        preview_review(snapshot, request(snapshot, (indep, "x")))


def test_unresolvable_source_ref_blocks_every_field():
    def bad_ref(data, base):
        data["entities"][0]["properties"] = {"source_refs": ["no-such-evidence-or-node"]}

    fields = review_fields(linked(bad_ref))
    assert not any(f.editable for f in fields)
    assert all("belirlenemediği" in f.blocked_reason for f in fields)


def test_source_ref_to_node_blocks_only_that_node():
    def ref(data, base):
        target = next(n for n in data["structure"] if n["identity_key"] == "review:indep")
        data["entities"][0]["properties"] = {"source_refs": [target["id"]]}

    snapshot = linked(ref)
    assert not node_fields(snapshot, "review:indep")[0].editable
    assert node_fields(snapshot, "review:table")[0].editable


def test_formula_and_compound_cells_keep_their_own_readonly_reasons():
    snapshot = linked()
    cells = node_fields(snapshot, "review:table")
    # (1,0) formula and (1,2) list cite the free container, so their own reason must remain.
    assert not cells[3].editable and "Formül" in cells[3].blocked_reason
    assert not cells[5].editable and "Liste" in cells[5].blocked_reason
    assert "ilişkili" not in cells[3].blocked_reason
    before = snapshot.model_dump(mode="json")
    cell = cells[0]
    result = build_review_revision(snapshot, prepared(snapshot, (cell, "Alpha corrected")))
    old = next(n for n in before["structure"] if n["identity_key"] == "review:table")
    new = next(n.model_dump(mode="json") for n in result.structure if n.identity_key == "review:table")
    assert new["rows"][1] == old["rows"][1]  # formula, cache and list cells untouched
    assert new["rows"][0][1:] == old["rows"][0][1:]


def test_two_edits_with_one_affected_are_rejected_without_a_partial_preview():
    snapshot = linked()
    free = node_fields(snapshot, "review:indep")[0]
    affected = node_fields(snapshot, "review:text")[0]
    with pytest.raises(ValueError, match="read-only"):
        preview_review(snapshot, request(snapshot, (free, "a"), (affected, "b")))
    with pytest.raises(ValueError, match="read-only"):
        build_review_revision(snapshot, prepared(snapshot, (free, "a")).model_copy(
            update={"changes": request(snapshot, (free, "a"), (affected, "b")).changes}))
    assert preview_review(snapshot, request(snapshot, (free, "a"))).changes[0].field_id == free.field_id


def test_document_source_ref_blocks_descendants():
    snapshot = linked(lambda data, base: data["entities"][0].update(properties={"source_refs": [base.root_node_id]}))
    assert not any(field.editable for field in review_fields(snapshot))


@pytest.mark.parametrize("left,right,expected", [
    ({"kind": "text_span", "start": 0, "end": 5}, {"kind": "text_span", "start": 5, "end": 10}, "disjoint"),
    ({"kind": "text_span", "start": 0, "end": 5}, {"kind": "text_span", "start": 4, "end": 10}, "overlap"),
    ({"kind": "spreadsheet_range", "sheet": "Sheet1", "a1_range": "A1:B2"},
     {"kind": "spreadsheet_range", "sheet": "Sheet1", "a1_range": "C1:D2"}, "disjoint"),
    ({"kind": "spreadsheet_range", "sheet": "Sheet1", "a1_range": "A1:B2"},
     {"kind": "spreadsheet_range", "sheet": "Sheet1", "a1_range": "B2:C3"}, "overlap"),
    ({"kind": "docx_block", "part": "word/document.xml", "path": "/body/p[1]"},
     {"kind": "docx_block", "part": "word/document.xml", "path": "/body/p[10]"}, "disjoint"),
    ({"kind": "docx_block", "part": "word/document.xml", "path": "/body"},
     {"kind": "docx_block", "part": "word/document.xml", "path": "/body/p[10]"}, "overlap"),
])
def test_dependency_location_boundaries(left, right, expected):
    from docgrain_domain.canonical.review import _locators_relate
    assert _locators_relate(left, right) == expected
