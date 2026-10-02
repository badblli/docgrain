"""Manual revision review: pure typed previews and deterministic child revisions."""

from datetime import UTC, datetime

import pytest
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot, deterministic_item_id
from docgrain_domain.canonical.lifecycle import (
    ProcessingSpec,
    digest,
    processing_revision_id,
    scoped_id,
)
from docgrain_domain.canonical.review import (
    ReviewChange,
    ReviewRequest,
    SaveReviewRequest,
    build_review_revision,
    preview_review,
    review_fields,
)

from tests.fixtures.lifecycle import mapped_snapshot
from tests.unit.test_n3_visuals import visual_snapshot

OCCURRED = datetime(2026, 10, 2, 21, 0, tzinfo=UTC)


def annotation(snapshot, evidence=True):
    return {
        "provenance": {
            "method": "parser",
            "derivation": "direct",
            "producer_id": snapshot.knowledge_revision.producers[0].id,
            "evidence_ids": [snapshot.evidence[0].id] if evidence else [],
            "confidence": None,
        },
        "review_status": "unreviewed",
    }


def node(snapshot, kind, key, **fields):
    return {
        "id": deterministic_item_id(
            snapshot.document_id, kind, key, policy_version=snapshot.identity_policy_version
        ),
        "identity_key": key,
        "kind": kind,
        **fields,
    }


def with_nodes(snapshot, nodes):
    data = snapshot.model_dump(mode="json")
    data.update(entities=[], relations=[], records=[])
    root = next(n for n in data["structure"] if n["id"] == data["root_node_id"])
    for item in nodes:
        data["structure"].append(item)
        root["children"].append(item["id"])
    return CanonicalKnowledgeSnapshot.model_validate(data)


def reviewable(snapshot, cells, **extra):
    """Adds a text block, an evidence-less text block and a table to a snapshot."""
    return with_nodes(
        snapshot,
        [
            node(snapshot, "text_block", "review:text", text="Original text", role="paragraph",
                 annotation=annotation(snapshot)),
            node(snapshot, "text_block", "review:text-bare", text="No evidence", role="paragraph",
                 annotation=annotation(snapshot, evidence=False)),
            node(snapshot, "table", "review:table", rows=cells, annotation=annotation(snapshot)),
            *extra.get("nodes", []),
        ],
    )


def legacy():
    base, _, _ = visual_snapshot()
    cells = [
        [
            {"value": "Alpha"},
            {"value": 5, "display_text": "5 units"},
            {"value": None},
        ],
        [
            {"value": 3, "formula": "=B1-2", "cached_value": 3, "display_text": "3"},
            {"value": True},
            {"value": [1, 2]},
        ],
    ]
    bare_asset = node(base, "asset", "review:asset-bare", artifact_id=base.artifacts[0].id,
                      description=None, annotation=annotation(base, evidence=False))
    return reviewable(base, cells, nodes=[bare_asset])


def modern():
    base = mapped_snapshot()[0]
    data = base.model_dump(mode="json")
    spec = ProcessingSpec.model_validate(
        {**data["knowledge_revision"]["processing"], "schema_version": "0.6.0"}
    )
    revision = data["knowledge_revision"]
    revision.update(
        id=processing_revision_id(data["source_version"]["id"], spec),
        processing=spec.model_dump(mode="json"),
        producers=[{**p, "configuration_digest": spec.digest} for p in revision["producers"]],
    )
    data["schema_version"] = "0.6.0"
    base = CanonicalKnowledgeSnapshot.model_validate(data)
    cells = [
        [
            {"value": "Left", "source_attributes": {"covered": False}},
            {"value": "Hidden", "source_attributes": {"covered": True}},
            {"value": "Kept", "source_attributes": {"covered": True},
             "annotation": annotation(base)},
        ]
    ]
    return reviewable(base, cells)


def node_fields(snapshot, key=None, kind=None):
    fields = review_fields(snapshot)
    if key is not None:
        node_id = next(n.id for n in snapshot.structure if n.identity_key == key)
        fields = [f for f in fields if f.node_id == node_id]
    return [f for f in fields if kind is None or f.kind == kind]


def request(snapshot, *changes, **override):
    values = {
        "base_revision_id": snapshot.knowledge_revision.id,
        "base_snapshot_sha256": digest(snapshot.model_dump(mode="json")),
        "operation_id": "operation-1",
        "occurred_at": OCCURRED,
        "reviewer_id": "reviewer",
        "reason": "Checked against the source page",
        "changes": [{"field_id": f.field_id, "before": f.value, "after": after} for f, after in changes],
    }
    values.update(override)
    return ReviewRequest(**values)


def request_sha(req):
    value = req.model_dump(mode="json", exclude={"preview_id", "confirmed_source"})
    value["changes"] = sorted(value["changes"], key=lambda c: c["field_id"])
    return digest(value)


def prepared(snapshot, *changes, **override):
    """A save request bound to the preview the server would have issued."""
    req = request(snapshot, *changes, **override)
    values = req.model_dump()
    values.update(preview_id=preview_review(snapshot, req).proposal_id, confirmed_source=True)
    return SaveReviewRequest(**values)


def test_fields_expose_every_cell_row_major_with_explicit_blocks():
    snapshot = legacy()
    cells = node_fields(snapshot, "review:table")
    assert [f.label for f in cells] == [f"Hücre · satır {r}, sütun {c}" for r in (1, 2) for c in (1, 2, 3)]
    assert [f.editable for f in cells] == [True, True, True, False, True, False]
    assert [f.value for f in cells][:3] == ["Alpha", 5, None]
    assert "Formül" in cells[3].blocked_reason and "Liste" in cells[5].blocked_reason
    assert all((f.blocked_reason is None) == f.editable for f in review_fields(snapshot))
    assert node_fields(snapshot, "review:text")[0].editable
    assert not node_fields(snapshot, "review:text-bare")[0].editable
    assert not node_fields(snapshot, "review:asset-bare")[0].editable
    assert all(f.editable for f in node_fields(snapshot, kind="description")[:2])
    ids = [f.field_id for f in review_fields(snapshot)]
    assert len(ids) == len(set(ids)) and ids == [f.field_id for f in review_fields(snapshot)]


def test_covered_cells_are_readonly_even_with_an_annotation():
    fields = node_fields(modern(), "review:table")
    assert [f.editable for f in fields] == [True, False, False]
    assert "Birleşik" in fields[1].blocked_reason


def test_preview_is_pure_typed_and_deterministic():
    snapshot = legacy()
    before = snapshot.model_dump(mode="json")
    text = node_fields(snapshot, "review:text")[0]
    cells = node_fields(snapshot, "review:table")
    description = node_fields(snapshot, kind="description")[0]
    req = request(snapshot, (text, "Corrected text"), (cells[1], 6), (cells[2], 1.5),
                  (cells[4], False), (description, "A site plan"))
    preview = preview_review(snapshot, req)
    assert snapshot.model_dump(mode="json") == before
    assert preview == preview_review(snapshot, req)
    assert preview.review_status == "proposed" and len(preview.changes) == 5
    assert [d.field_id for d in preview.changes] == [
        f.field_id for f in review_fields(snapshot)
        if f.field_id in {c.field_id for c in req.changes}
    ]
    assert any("bütünü" in w for w in preview.warnings)
    assert any("embedding" in w for w in preview.warnings)
    reordered = req.model_copy(update={"changes": list(reversed(req.changes))})
    assert preview_review(snapshot, reordered).proposal_id == preview.proposal_id
    assert preview_review(snapshot, req.model_copy(update={"reason": "Other"})).proposal_id != preview.proposal_id


def test_blank_descriptions_are_allowed_edits_but_unresolved():
    snapshot = legacy()
    description = node_fields(snapshot, kind="description")[0]
    preview = preview_review(snapshot, request(snapshot, (description, "x")))
    assert preview.changes[0].after == "x"
    first = build_review_revision(snapshot, prepared(snapshot, (description, "x")))
    again = node_fields(first, kind="description")[0]
    assert again.value == "x"
    assert preview_review(first, request(first, (again, None))).changes[0].after is None
    assert preview_review(first, request(first, (again, ""))).changes[0].after == ""
    cleared = build_review_revision(first, prepared(first, (again, None)))
    assert next(n for n in cleared.structure if n.id == description.node_id).description is None
    assert cleared.knowledge_revision.coverage == snapshot.knowledge_revision.coverage


@pytest.mark.parametrize(
    "index,after",
    [(1, "five"), (1, 5.5), (1, True), (4, 1), (4, "yes"), (0, 3), (0, None)],
)
def test_cell_after_must_keep_the_scalar_type(index, after):
    snapshot = legacy()
    cell = node_fields(snapshot, "review:table")[index]
    with pytest.raises(ValueError, match="type is not allowed"):
        preview_review(snapshot, request(snapshot, (cell, after)))


def test_null_cell_may_become_any_scalar_and_text_never_null():
    snapshot = legacy()
    empty = node_fields(snapshot, "review:table")[2]
    for after in ("a", 1, 2.5, True):
        assert preview_review(snapshot, request(snapshot, (empty, after))).changes[0].after == after
    text = node_fields(snapshot, "review:text")[0]
    with pytest.raises(ValueError, match="type is not allowed"):
        preview_review(snapshot, request(snapshot, (text, None)))
    with pytest.raises(ValueError, match="type is not allowed"):
        preview_review(snapshot, request(snapshot, (text, 7)))


def test_malformed_values_never_reach_the_domain():
    for bad in (float("nan"), float("inf"), ["a"], {"a": 1}):
        with pytest.raises(ValueError):
            ReviewChange(field_id="f", before="x", after=bad)


def test_readonly_and_unsafe_targets_are_rejected():
    snapshot = legacy()
    cells = node_fields(snapshot, "review:table")
    for field in (cells[3], cells[5], node_fields(snapshot, "review:text-bare")[0],
                  node_fields(snapshot, "review:asset-bare")[0]):
        with pytest.raises(ValueError, match="read-only"):
            preview_review(snapshot, request(snapshot, (field, "changed")))
    covered = node_fields(modern(), "review:table")[1]
    snap = modern()
    with pytest.raises(ValueError, match="read-only"):
        preview_review(snap, request(snap, (covered, "changed")))


def test_oversized_values_are_readonly_and_total_is_limited():
    base = legacy()
    big = "x" * 100_001
    snapshot = with_nodes(base, [
        node(base, "text_block", "review:big", text=big, role="paragraph", annotation=annotation(base)),
        node(base, "text_block", "review:one", text="a", role="paragraph", annotation=annotation(base)),
        node(base, "text_block", "review:two", text="b", role="paragraph", annotation=annotation(base)),
        node(base, "text_block", "review:three", text="c", role="paragraph", annotation=annotation(base)),
    ])
    assert not node_fields(snapshot, "review:big")[0].editable
    with pytest.raises(ValueError, match="read-only"):
        preview_review(snapshot, request(snapshot, (node_fields(snapshot, "review:big")[0], "small")))
    fields = [node_fields(snapshot, k)[0] for k in ("review:one", "review:two", "review:three")]
    with pytest.raises(ValueError, match="total"):
        preview_review(snapshot, request(snapshot, *[(f, "y" * 100_000) for f in fields]))
    with pytest.raises(ValueError, match="exceeds"):
        preview_review(snapshot, request(snapshot, (fields[0], "y" * 100_001)))


def test_stale_base_hash_and_before_are_rejected():
    snapshot = legacy()
    text = node_fields(snapshot, "review:text")[0]
    with pytest.raises(ValueError, match="another source or processing revision"):
        preview_review(snapshot, request(snapshot, (text, "x"), base_revision_id="other"))
    with pytest.raises(ValueError, match="another source or processing revision"):
        preview_review(snapshot, request(snapshot, (text, "x"), base_snapshot_sha256="0" * 64))
    with pytest.raises(ValueError, match="stale"):
        preview_review(snapshot, request(snapshot, (text.model_copy(update={"value": "Old"}), "x")))
    number = node_fields(snapshot, "review:table")[1]
    for wrong in (5.0, "5", True):  # equal-looking values of a different type are stale
        with pytest.raises(ValueError, match="stale"):
            preview_review(snapshot, request(snapshot, (number.model_copy(update={"value": wrong}), 6)))
    flag = node_fields(snapshot, "review:table")[4]
    with pytest.raises(ValueError, match="stale"):
        preview_review(snapshot, request(snapshot, (flag.model_copy(update={"value": 1}), False)))


def test_noop_duplicate_unknown_and_arbitrary_fields_are_rejected():
    snapshot = legacy()
    text = node_fields(snapshot, "review:text")[0]
    with pytest.raises(ValueError, match="does not alter"):
        preview_review(snapshot, request(snapshot, (text, "Original text")))
    with pytest.raises(ValueError, match="duplicate"):
        preview_review(snapshot, request(snapshot, (text, "a"), (text, "b")))
    for field_id in ("missing", "/structure/0/text", "/structure/1/annotation/review_status"):
        bad = request(snapshot, (text, "a"))
        bad = bad.model_copy(update={"changes": [ReviewChange(field_id=field_id, before="x", after="y")]})
        with pytest.raises(ValueError, match="unknown review field"):
            preview_review(snapshot, bad)
    other = modern()
    foreign = node_fields(other, "review:text")[0]
    with pytest.raises(ValueError, match="unknown review field"):
        preview_review(snapshot, request(snapshot, (foreign, "x")))


def test_model_copy_mutations_are_revalidated():
    snapshot = legacy()
    text = node_fields(snapshot, "review:text")[0]
    req = request(snapshot, (text, "x"))
    for update in ({"changes": []}, {"reviewer_id": "  "}, {"reason": ""}, {"operation_id": "o" * 129},
                   {"base_snapshot_sha256": "ABC"}, {"occurred_at": datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)}):
        with pytest.raises(ValueError):
            preview_review(snapshot, req.model_copy(update=update))
    broken = snapshot.model_copy(update={"root_node_id": "missing"})
    with pytest.raises(ValueError):
        preview_review(broken, req)
    with pytest.raises(ValueError):
        review_fields(broken)
    mutated = snapshot.model_copy(deep=True)
    mutated.structure[0].annotation.provenance.producer_id = "unknown-producer"
    with pytest.raises(ValueError):
        preview_review(mutated, req)


def test_linked_facts_make_every_field_readonly_and_preview_fails():
    base = legacy()
    data = base.model_dump(mode="json")
    data["entities"] = [{
        "id": "entity-1", "identity_key": "entity:1", "type": "Thing", "label": "Thing",
        "annotation": annotation(base),
    }]
    snapshot = CanonicalKnowledgeSnapshot.model_validate(data)
    fields = review_fields(snapshot)
    assert fields and not any(f.editable for f in fields)
    assert all(f.blocked_reason and "ilişkili" in f.blocked_reason for f in fields)
    text = node_fields(snapshot, "review:text")[0]
    with pytest.raises(ValueError, match="read-only"):
        preview_review(snapshot, request(snapshot, (text, "x")))


def test_save_requires_confirmation_and_the_exact_preview():
    snapshot = legacy()
    text = node_fields(snapshot, "review:text")[0]
    good = prepared(snapshot, (text, "Corrected"))
    with pytest.raises(ValueError):
        build_review_revision(snapshot, good.model_copy(update={"confirmed_source": False}))
    with pytest.raises(ValueError, match="preview"):
        build_review_revision(snapshot, good.model_copy(update={"preview_id": "review_proposal_x"}))
    with pytest.raises(ValueError, match="preview"):
        build_review_revision(snapshot, good.model_copy(update={"reason": "A different reason"}))
    plain = request(snapshot, (text, "Corrected"))
    with pytest.raises(ValueError):
        build_review_revision(snapshot, plain)
    assert build_review_revision(snapshot, good).structure


def test_legacy_revision_keeps_schema_source_and_node_identity():
    snapshot = legacy()
    before = snapshot.model_dump(mode="json")
    text = node_fields(snapshot, "review:text")[0]
    cells = node_fields(snapshot, "review:table")
    description = node_fields(snapshot, kind="description")[0]
    req = prepared(snapshot, (text, "Corrected"), (cells[1], 6), (description, "Site plan"))
    result = build_review_revision(snapshot, req)
    assert snapshot.model_dump(mode="json") == before
    parent = snapshot.knowledge_revision
    revision = result.knowledge_revision
    sha = request_sha(req)
    assert revision.id == scoped_id("revision", [parent.id, "manual-review-1", sha])
    assert revision.parent_revision_id == parent.id and revision.created_at == OCCURRED
    assert revision.processing is None and result.schema_version == snapshot.schema_version
    assert result.identity_policy_version == snapshot.identity_policy_version
    assert result.source_version == snapshot.source_version
    assert result.evidence == snapshot.evidence and result.artifacts == snapshot.artifacts
    assert [n.id for n in result.structure] == [n.id for n in snapshot.structure]
    assert revision.coverage == parent.coverage
    assert revision.producers[:-1] == parent.producers
    producer = revision.producers[-1]
    assert (producer.name, producer.version) == ("Docgrain source review", "1")
    assert producer.id not in {p.id for p in parent.producers}

    new_text = next(n for n in result.structure if n.identity_key == "review:text")
    assert new_text.text == "Corrected"
    for ann in (new_text.annotation, new_text.field_annotations["/text"]):
        assert (ann.review_status, ann.provenance.method, ann.provenance.derivation) == (
            "approved", "manual", "overridden")
        assert ann.provenance.producer_id == producer.id and ann.provenance.confidence is None
        assert ann.provenance.evidence_ids == text.evidence_ids
    new_asset = next(n for n in result.structure if n.id == description.node_id)
    assert new_asset.description == "Site plan"
    assert new_asset.field_annotations["/description"].provenance.derivation == "visual_description"
    assert new_asset.annotation.review_status == "approved"

    table = next(n for n in result.structure if n.identity_key == "review:table")
    old_table = next(n for n in snapshot.structure if n.identity_key == "review:table")
    changed = table.rows[0][1]
    assert changed.value == 6 and changed.display_text is None
    assert changed.annotation.review_status == "approved" and changed.annotation.provenance.method == "manual"
    assert table.rows[1][0] == old_table.rows[1][0]  # formula/cache/display untouched
    assert table.rows[0][0] == old_table.rows[0][0]

    event = result.metadata["manual_review"]
    assert event["operation_id"] == "operation-1" and event["request_sha256"] == sha
    assert event["reviewer_id"] == "reviewer" and event["reason"] == req.reason
    assert event["base_revision_id"] == parent.id and event["confirmed_source"] is True
    assert event["source_sha256"] == snapshot.source_version.content_sha256
    assert event["occurred_at"] == req.model_dump(mode="json")["occurred_at"]
    by_kind = {c["kind"]: c for c in event["changes"]}
    assert by_kind["text"]["before"] == "Original text" and by_kind["text"]["after"] == "Corrected"
    assert by_kind["table_cell"]["previous_display_text"] == "5 units"
    assert by_kind["table_cell"]["previous_annotation"] is None
    assert by_kind["text"]["previous_annotation"]["provenance"]["method"] == "parser"
    assert by_kind["description"]["before"] is None


def test_modern_revision_keeps_schema_source_and_processing_lineage():
    snapshot = modern()
    assert snapshot.schema_version == "0.6.0"
    before = snapshot.model_dump(mode="json")
    text = node_fields(snapshot, "review:text")[0]
    cell = node_fields(snapshot, "review:table")[0]
    req = prepared(snapshot, (text, "Corrected"), (cell, "Right"))
    result = build_review_revision(snapshot, req)
    assert snapshot.model_dump(mode="json") == before
    parent = snapshot.knowledge_revision
    spec = result.knowledge_revision.processing
    sha = request_sha(req)
    assert result.schema_version == snapshot.schema_version == spec.schema_version
    assert result.source_version == snapshot.source_version
    assert result.evidence == snapshot.evidence and result.artifacts == snapshot.artifacts
    assert [n.id for n in result.structure] == [n.id for n in snapshot.structure]
    assert spec.options["manual_review"] == {
        "base_revision_id": parent.id, "contract_version": "review-1", "request_sha256": sha}
    assert {k: v for k, v in spec.options.items() if k != "manual_review"} == parent.processing.options
    assert spec.digest != parent.processing.digest
    assert result.knowledge_revision.id == processing_revision_id(result.source_version.id, spec)
    assert result.knowledge_revision.id != parent.id
    assert result.knowledge_revision.parent_revision_id == parent.id
    assert all(p.configuration_digest == spec.digest for p in result.knowledge_revision.producers)
    assert all(p.configuration_digest == parent.processing.digest for p in parent.producers)
    assert result.knowledge_revision.producers[-1].name == "Docgrain source review"
    assert result.knowledge_revision.coverage == parent.coverage
    assert result.metadata["manual_review"]["request_sha256"] == sha
    # The result is itself a reviewable base for a later review.
    again = node_fields(result, "review:text")[0]
    assert again.value == "Corrected"
    follow = build_review_revision(result, prepared(result, (again, "Corrected twice")))
    assert follow.knowledge_revision.parent_revision_id == result.knowledge_revision.id


def test_replay_is_deterministic_and_changed_operation_reviewer_or_reason_is_distinct():
    snapshot = legacy()
    text = node_fields(snapshot, "review:text")[0]
    first = build_review_revision(snapshot, prepared(snapshot, (text, "Corrected")))
    replay = build_review_revision(snapshot, prepared(snapshot, (text, "Corrected")))
    assert first.model_dump(mode="json") == replay.model_dump(mode="json")
    ids = {first.knowledge_revision.id}
    for override in ({"operation_id": "operation-2"}, {"reviewer_id": "someone-else"},
                     {"reason": "A different reason"}):
        other = build_review_revision(snapshot, prepared(snapshot, (text, "Corrected"), **override))
        ids.add(other.knowledge_revision.id)
    other = build_review_revision(snapshot, prepared(snapshot, (text, "Different")))
    ids.add(other.knowledge_revision.id)
    assert len(ids) == 5


@pytest.mark.parametrize("confirmation", [1, "true", False, None])
def test_confirmation_requires_actual_boolean(confirmation):
    snapshot = legacy()
    text = node_fields(snapshot, "review:text")[0]
    with pytest.raises(ValueError):
        SaveReviewRequest.model_validate({**prepared(snapshot, (text, "changed")).model_dump(),
                                         "confirmed_source": confirmation})


def test_native_merge_marker_and_span_coverage_are_not_editable():
    base = modern()
    data = base.model_dump(mode="json")
    table = next(n for n in data["structure"] if n["identity_key"] == "review:table")
    table["rows"] = [[{"value": "Head", "col_span": 2}, {"value": "Hidden"},
                      {"value": None, "source_attributes": {"merge_covered": True}}]]
    fields = node_fields(CanonicalKnowledgeSnapshot.model_validate(data), "review:table")
    assert [f.editable for f in fields] == [True, False, False]


def test_browser_integral_float_serialization_keeps_source_float_type():
    base = modern()
    data = base.model_dump(mode="json")
    table = next(n for n in data["structure"] if n["identity_key"] == "review:table")
    table["rows"] = [[{"value": 1.0}]]
    snapshot = CanonicalKnowledgeSnapshot.model_validate(data)
    field = node_fields(snapshot, "review:table")[0]
    req = request(snapshot, (field, 2)).model_copy(update={
        "changes": [ReviewChange(field_id=field.field_id, before=1, after=2)]})
    preview = preview_review(snapshot, req)
    save = SaveReviewRequest(**req.model_dump(), preview_id=preview.proposal_id, confirmed_source=True)
    result = build_review_revision(snapshot, save)
    assert type(next(n for n in result.structure if n.id == field.node_id).rows[0][0].value) is float
    assert result.metadata["manual_review"]["changes"][0]["after"] == 2.0
