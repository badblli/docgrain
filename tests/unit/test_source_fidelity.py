from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot, deterministic_item_id
from docgrain_worker.fidelity import audit_source, golden_table_checks
from docgrain_worker.selective_vision import (
    GeminiSelectedExtractor,
    Observation,
    prepare_request,
    render_table_page,
    save_proposal,
)
from docgrain_worker.visual_review import review_table_proposal

from tests.fixtures.canonical.generate import annotation, generic_pdf


def snapshot_for(data, extension="pdf"):
    value = generic_pdf()
    value["schema_version"] = "0.2.0"
    value["source_version"].update(content_sha256=sha256(data).hexdigest(),
                                   byte_size=len(data), filename=f"source.{extension}")
    return CanonicalKnowledgeSnapshot.model_validate(value)


def check(snapshot, row, column, expected):
    table = next(n for n in snapshot.structure if n.kind == "table")
    return {"revision_id": snapshot.knowledge_revision.id,
            "source_sha256": snapshot.source_version.content_sha256,
            "node_id": table.id, "row": row, "column": column, "expected": expected}


@pytest.fixture
def pdf_review():
    pymupdf = pytest.importorskip("pymupdf")
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 40), "Site Samples Izmir 12")
        data = doc.tobytes()
    snapshot = snapshot_for(data)
    node = next(n for n in snapshot.structure if n.kind == "table")
    image = render_table_page(data, 1)
    request = prepare_request(snapshot, node.id, image, task="table", source_bytes=data,
                              context="Upper table", input_locator={"kind": "pdf_page_render", "page_number": 1})
    return snapshot, data, image, request


def test_source_bytes_and_negative_golden_binding_are_enforced(tmp_path):
    snapshot = snapshot_for(b"original", "txt")
    path = tmp_path / "source.txt"
    path.write_bytes(b"changed!")
    with pytest.raises(ValueError, match="checksum/size"):
        audit_source(snapshot, path)
    assertion = check(snapshot, 0, 0, "Site")
    assertion["revision_id"] = "different"
    with pytest.raises(ValueError, match="another source/revision"):
        golden_table_checks(snapshot, [assertion])
    assertion = check(snapshot, -1, 0, "Site")
    with pytest.raises(ValueError, match="nonnegative"):
        golden_table_checks(snapshot, [assertion])


def test_table_column_swap_fails_even_when_all_words_survive():
    snapshot = snapshot_for(b"PDF")
    before = snapshot.model_dump(mode="json")
    assertions = [check(snapshot, 0, 0, "Samples"), check(snapshot, 0, 1, "Site")]
    assert not any(c["matches"] for c in golden_table_checks(snapshot, assertions))
    assert not golden_table_checks(snapshot, [check(snapshot, 20, 0, None)])[0]["matches"]
    assert snapshot.model_dump(mode="json") == before


def test_txt_whitespace_normalization_does_not_certify_meaning(tmp_path):
    data = "Summary\nİzmir site recorded 12 samples.\nSite Samples İzmir 12".encode()
    snapshot = snapshot_for(data, "txt")
    path = tmp_path / "source.txt"
    path.write_bytes(data)
    report = audit_source(snapshot, path)
    assert report["checks"]["normalized_equal"]
    assert report["semantic_acceptance"] == "not_certified"


def test_docx_repeated_paragraph_occurrences_are_not_hidden(tmp_path):
    text = "İzmir site recorded 12 samples."
    paragraph = f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
    xml = f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{paragraph * 2}</w:body></w:document>'
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", xml)
    data = stream.getvalue()
    path = tmp_path / "source.docx"
    path.write_bytes(data)
    result = audit_source(snapshot_for(data, "docx"), path)
    assert result["checks"]["source_paragraphs"] == 2
    assert result["checks"]["matched_occurrences"] == 1
    assert result["checks"]["missing"] == {text: 1}


def test_xlsx_detects_coordinate_swap_and_preserves_raw_formula(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["Site", "Samples"])
    sheet.append(["İzmir", "=6+6"])
    stream = BytesIO()
    workbook.save(stream)
    data = stream.getvalue()
    value = snapshot_for(data, "xlsx").model_dump(mode="json")
    for evidence in value["evidence"]:
        if evidence["id"].startswith("evidence-cell-"):
            evidence["locator"] = {"kind": "spreadsheet_range", "sheet": "Data",
                                   "a1_range": evidence["id"].split("-")[-1].upper()}
    table = next(n for n in value["structure"] if n["kind"] == "table")
    table["rows"][1][1].update(value=None, formula="=6+6", cached_value=None)
    path = tmp_path / "source.xlsx"
    path.write_bytes(data)
    assert not audit_source(CanonicalKnowledgeSnapshot.model_validate(value), path)["checks"]["mismatches"]
    table["rows"][0].reverse()
    # Swap the values while retaining evidence locations to simulate a bad mapper.
    table["rows"][0][0]["annotation"], table["rows"][0][1]["annotation"] = (
        table["rows"][0][1]["annotation"], table["rows"][0][0]["annotation"])
    assert len(audit_source(CanonicalKnowledgeSnapshot.model_validate(value), path)["checks"]["mismatches"]) == 2


def test_pdf_overlap_is_diagnostic_and_image_substitution_rejected(pdf_review, tmp_path):
    snapshot, data, image, request = pdf_review
    path = tmp_path / "source.pdf"
    path.write_bytes(data)
    assert audit_source(snapshot, path)["semantic_acceptance"] == "not_certified"
    for supplied_image, locator in [(b"different PNG", request.input_locator),
                                     (image, {"kind": "pdf_page_render", "page_number": 2})]:
        with pytest.raises(ValueError):
            prepare_request(snapshot, request.target_node_id, supplied_image, task="table",
                            source_bytes=data, context="", input_locator=locator)


def test_asset_hash_size_and_locator_are_verified():
    source, image = b"source", b"PNG"
    value = snapshot_for(source).model_dump(mode="json")
    node_id = deterministic_item_id(value["document_id"], "asset", "plan")
    value["artifacts"] = [{"id": "plan-binary", "role": "picture", "storage_uri": "fixture://image",
                           "content_sha256": sha256(image).hexdigest(), "byte_size": len(image), "mime_type": "image/png"}]
    value["structure"].append({"id": node_id, "identity_key": "plan", "kind": "asset",
                               "artifact_id": "plan-binary", "annotation": annotation("evidence-page-1")})
    value["structure"][0]["children"].append(node_id)
    snapshot = CanonicalKnowledgeSnapshot.model_validate(value)
    kwargs = dict(task="room_plan", source_bytes=source, context="", input_locator={"kind": "artifact", "artifact_id": "plan-binary"})
    assert prepare_request(snapshot, node_id, image, **kwargs).task == "room_plan"
    with pytest.raises(ValueError, match="canonical asset"):
        prepare_request(snapshot, node_id, b"bad", **kwargs)
    kwargs["input_locator"]["artifact_id"] = "other"
    with pytest.raises(ValueError, match="locator mismatch"):
        prepare_request(snapshot, node_id, image, **kwargs)


@pytest.mark.parametrize("rows", [[["a"], ["a", "b"]], [[]], [["a"] * 10001]])
def test_invalid_provider_table_geometry_rejected(rows):
    with pytest.raises(ValueError):
        Observation(visible_text=[], visual_description="", table_rows=rows, uncertainties=[])


def test_mocked_provider_rejects_bad_json_and_no_table_before_saving(pdf_review, tmp_path, monkeypatch):
    import sys
    from types import ModuleType
    google = ModuleType("google")
    genai = ModuleType("google.genai")
    genai.types = SimpleNamespace(Part=SimpleNamespace(from_bytes=lambda **kw: kw),
                                 GenerateContentConfig=lambda **kw: kw,
                                 AutomaticFunctionCallingConfig=lambda **kw: kw)
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    _, _, image, request = pdf_review
    extractor = GeminiSelectedExtractor.__new__(GeminiSelectedExtractor)
    extractor.model = "test-model"
    response = SimpleNamespace(text="bad JSON", model_version="test-model", usage_metadata=None)
    extractor.client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **_: response))
    with pytest.raises(ValueError):
        extractor.extract(request, image)
    response.text = Observation(visible_text=[], visual_description="", table_rows=[], uncertainties=[]).model_dump_json()
    with pytest.raises(ValueError, match="no table"):
        extractor.extract(request, image)
    response.text = Observation(visible_text=[], visual_description="", table_rows=[["a"]], uncertainties=[]).model_dump_json()
    proposal = extractor.extract(request, image)
    assert proposal["review_status"] == "proposed"
    assert proposal["request"]["input_sha256"] == sha256(image).hexdigest()
    path = tmp_path / "proposal.json"
    save_proposal(path, proposal)
    save_proposal(path, proposal)
    with pytest.raises(ValueError, match="overwriting"):
        save_proposal(path, {**proposal, "review_status": "approved"})
    with pytest.raises(ValueError, match="changed before"):
        extractor.extract(request, b"swapped")


def test_only_independently_checked_changes_enter_preview(pdf_review):
    snapshot, data, _, request = pdf_review
    original = snapshot.model_dump(mode="json")
    proposal = {"request": request.model_dump(mode="json"), "observation": {
        "visible_text": [], "visual_description": "", "uncertainties": [],
        "table_rows": [["Sites", "Number"], ["Izmir", "12"]]}}
    assertions = [check(snapshot, 0, 0, "Site"), check(snapshot, 0, 1, "Number")]
    result = review_table_proposal(snapshot, proposal, data, assertions)
    assert [d["decision"] for d in result["decisions"]] == [
        "rejected", "source_checked", "needs_source_review", "needs_source_review"]
    assert result["preview_rows"] == [["Site", "Number"], ["İzmir", 12]]
    assert all(c["matches"] for c in result["golden_after"])
    assert snapshot.model_dump(mode="json") == original
    bad = deepcopy(proposal)
    bad["request"]["revision_id"] = "stale"
    with pytest.raises(ValueError, match="binding differs"):
        review_table_proposal(snapshot, bad, data, assertions)
    bad = deepcopy(proposal)
    bad["observation"]["table_rows"].append(["new", "row"])
    with pytest.raises(ValueError, match="shape changes"):
        review_table_proposal(snapshot, bad, data, assertions)
