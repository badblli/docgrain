"""WP119 (decision 21): the records job builds collections from Docling structure first.

Synthetic documents only. The Docling JSON is the same plain export ``structure_units`` reads
(docling-core is not installed on the host); contexts are compact ``[§N p.X]`` projections.
No real model: the model path uses a fake HTTP transport and is asserted to stay unused when the
structure is enough or the workspace model is off.
"""

import json
import re
from copy import deepcopy
from types import SimpleNamespace

import httpx
import test_u1_pipeline
from docgrain_api import records_jobs as lifecycle
from docgrain_records.discovery_models import DiscoveryDocument
from docgrain_records.structure_records import (
    build_structure_plan,
    collection_key,
    field_key,
    reduced_context,
)
from docgrain_records.structure_units import group_units, structure_units
from docgrain_worker import records_pipeline as pipeline
from test_u1_pipeline import BASE, WORKSPACE, start

setup = test_u1_pipeline.setup  # the shared U1 fixture (fake jobs, store, settings)

# --------------------------------------------------------------------------- synthetic sources


def cell(r, c, text, header=False):
    return {"text": text, "row_span": 1, "col_span": 1, "start_row_offset_idx": r,
            "end_row_offset_idx": r + 1, "start_col_offset_idx": c, "end_col_offset_idx": c + 1,
            "column_header": header, "row_header": False, "row_section": False}


def table(index, rows, header_rows=1):
    cells = [cell(r, c, text, header=r < header_rows) for r, row in enumerate(rows)
             for c, text in enumerate(row)]
    return {"self_ref": f"#/tables/{index}", "label": "table", "children": [], "captions": [],
            "prov": [{"page_no": 1, "bbox": {"l": 0, "t": 0, "r": 1, "b": 1}, "charspan": [0, 0]}],
            "data": {"table_cells": cells, "num_rows": len(rows), "num_cols": len(rows[0])}}


def docling(body, texts=(), tables=(), groups=()):
    return {"schema_name": "DoclingDocument", "body": {"self_ref": "#/body", "children": body},
            "texts": list(texts), "tables": list(tables), "groups": list(groups),
            "key_value_items": []}


def heading(index, text, level=1, label="section_header"):
    return {"self_ref": f"#/texts/{index}", "label": label, "level": level, "text": text,
            "children": [], "prov": []}


def markdown(rows):
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
    return "\n".join(lines + ["| " + " | ".join(row) + " |" for row in rows[1:]])


def context(name, blocks):
    parts = [f"# {name}", "Çıkarılmış belge içeriği.", "doc · rev"]
    parts += [f"[§{i} p.{page}]\n{body}" for i, (page, body) in enumerate(blocks, 1)]
    parts += ["## Kaynak anahtarları", *[f"§{i} → node_{i}" for i in range(1, len(blocks) + 1)]]
    return "\n\n".join(parts) + "\n"


RESTAURANTS_PDF = [["Restoran", "Saat", "Mutfak"],
                   ["Lagoon Restaurant", "07:00-10:30", "Dünya mutfağı"],
                   ["Sunset Grill", "12:30-17:00", "Izgara"]]
RESTAURANTS_XLSX = [["Restoran", "Saat"],
                    ["Lagoon Restaurant", "07:00-11:00"],
                    ["Sunset Grill", "12:30-17:00"],
                    ["Beach Bar", "10:00-24:00"]]
SNACKS = [["Restoran", "Saat", "Konum", "Fiyat"],
          ["Pool Snack", "11:00-16:00", "Havuz", "50 TL"],
          ["Kiosk", "10:00-18:00", "Plaj", "30 TL"]]
PROSE = "Otelimizde evcil hayvan kabul edilmez."


def sources():
    """menu (PDF table + a weakly similar snack table), hours (XLSX sheet), about (prose only)."""
    menu = docling([{"$ref": "#/texts/0"}, {"$ref": "#/tables/0"}, {"$ref": "#/texts/1"},
                    {"$ref": "#/tables/1"}],
                   texts=[heading(0, "Restoranlar"), heading(1, "Atıştırmalık")],
                   tables=[table(0, RESTAURANTS_PDF), table(1, SNACKS)])
    hours = docling([{"$ref": "#/groups/0"}], tables=[table(0, RESTAURANTS_XLSX)],
                    groups=[{"self_ref": "#/groups/0", "label": "sheet", "name": "F&B saatleri",
                             "children": [{"$ref": "#/tables/0"}]}])
    contexts = {
        "menu": context("menu.pdf", [("1", "## Restoranlar"), ("1", markdown(RESTAURANTS_PDF)),
                                     ("2", "## Atıştırmalık"), ("2", markdown(SNACKS))]),
        "hours": context("hours.xlsx", [("F&B saatleri", markdown(RESTAURANTS_XLSX))]),
        "about": context("about.docx", [("¶1", "## Kurallar"), ("¶2", PROSE)]),
    }
    return contexts, {"menu": menu, "hours": hours, "about": None}


def discovery_document(key, text, lang="tr"):
    return DiscoveryDocument(source={
        "document_id": key, "workspace_id": WORKSPACE, "knowledge_revision_id": key + "-k1",
        "source_version_id": key + "-s1", "content_sha256": "a" * 64, "lang": lang,
        "filename": {"menu": "menu.pdf", "hours": "hours.xlsx", "about": "about.docx"}.get(key, key),
    }, context=text)


def use_sources(setup):
    """Replace the shared fixture's two documents with the three synthetic ones."""
    contexts, doclings = sources()
    setup.docs[:] = [discovery_document(key, contexts[key]) for key in sorted(contexts)]
    setup.metadata_docs[:] = [SimpleNamespace(id=key, workspace_id=WORKSPACE,
                                              latest_version_id=key + "-v1") for key in sorted(contexts)]
    for key in contexts:
        setup.versions[key] = SimpleNamespace(id=key + "-v1", status="done", workspace_id=WORKSPACE,
                                              content_sha256="a" * 64)
        setup.preparations[key + "-v1"] = SimpleNamespace(status="done", page_failures=[])
    return doclings


class PolicyModel:
    """Fake OpenAI-compatible endpoint that only knows the prose document's policy."""

    def __init__(self):
        self.calls = []

    def handle(self, request):
        payload = json.loads(request.content)
        self.calls.append(payload)
        user = json.loads(payload["messages"][1]["content"])
        labels = [{"lang": "en", "value": "Policies"}, {"lang": "tr", "value": "Kurallar"}]
        evidence = [{"document_id": "about", "locator": "§2", "quote": PROSE}]
        if payload["response_format"]["json_schema"]["name"] == "workspace_collections":
            blocks = {block["document_id"] for block in user["untrusted_source_blocks"]}
            assert blocks == {"about"}  # Only the document without usable structure.
            response = {"collections": [{
                "key": "policies", "label_i18n": labels, "description": "House rules.",
                "fields": [{"key": key, "type": "string", "unit": None, "label_i18n": labels}
                           for key in ("name", "text")],
                "examples": [{"values": [
                    {"key": "name", "value": "evcil hayvan", "lang": "tr", "evidence": evidence},
                    {"key": "text", "value": PROSE, "lang": "tr", "evidence": evidence}]}]}]}
        else:
            assert user["document_id"] == "about"
            focus = re.search(r"This pass extracts ONLY (\w+) records", payload["messages"][0]["content"])
            records = [] if focus and focus.group(1) != "policies" else [{
                "type": "policies",
                "name": [{"value": "evcil hayvan", "lang": "tr", "evidence": evidence}],
                "text": [{"value": PROSE, "lang": "tr", "evidence": evidence}]}]
            fields = {f["key"] for c in user.get("untrusted_collection_definitions", [])
                      if c["key"] == "policies" for f in c["fields"]}
            for record in records:
                for key in [k for k in record if k != "type" and fields and k not in fields]:
                    del record[key]
            response = {"records": records}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(response)}}]})


def run(setup, key, doclings, model=None):
    model = model or PolicyModel()
    pipeline.process_job(key, httpx.MockTransport(model.handle), lambda *_: deepcopy(setup.docs),
                         docling_loader=lambda *_: deepcopy(doclings))
    return setup.client.get(BASE + "/record-jobs/" + key).json(), model


def all_questions(setup):
    return setup.client.get(BASE + "/questions", params={"limit": 100}).json()["items"]


# --------------------------------------------------------------------------- acceptance


def test_pdf_table_and_xlsx_sheet_become_one_collection_with_conflict_and_merge_question(setup):
    doclings = use_sources(setup)
    setup.settings["enabled"] = False  # Model off: structure only, nothing leaves the machine.
    job, model = run(setup, start(setup), doclings)
    assert job["status"] == "done", job
    assert model.calls == []
    source = setup.store._source(WORKSPACE)
    schema = {c["key"]: c for c in source.workspace_schema["collections"]}
    assert set(schema) == {"restaurants", "atistirmalik_items"}
    assert [f["key"] for f in schema["restaurants"]["fields"]] == ["name", "hours", "mutfak"]
    assert [f["key"] for f in schema["atistirmalik_items"]["fields"]] == [
        "name", "hours", "location", "price"]
    assert schema["restaurants"]["label_i18n"] == [{"lang": "en", "value": "Restaurants"},
                                                   {"lang": "tr", "value": "Restoranlar"}]
    restaurants = [r for r in source.records if r.type == "restaurants"]
    names = {r.fields["name"].candidates[0].value: r for r in restaurants}
    assert sorted(names) == ["Beach Bar", "Lagoon Restaurant", "Sunset Grill"]
    lagoon = names["Lagoon Restaurant"]
    documents = {e.document_id for c in lagoon.fields["name"].candidates for e in c.evidence}
    assert documents == {"menu", "hours"}  # one record, both sources
    hours = {c.value: c for c in lagoon.fields["hours"].candidates}
    assert set(hours) == {"07:00-10:30", "07:00-11:00"}
    assert all(c.review_state == "needs_review" for c in hours.values())
    # Every value cites a table cell of its own document, checked by the verifier.
    cited = [e for r in source.records for f in r.fields.values() for c in f.candidates
             for e in c.evidence]
    assert cited and all(e.quote and " cell=" in e.locator for e in cited)
    sunset = names["Sunset Grill"].fields["hours"].candidates
    assert {c.review_state for c in sunset} == {"accepted"}  # agreeing sources (decision 20)

    items = all_questions(setup)
    kinds = sorted(q["kind"] for q in items)
    assert kinds == ["collection_merge", "conflict"]
    conflict = next(q for q in items if q["kind"] == "conflict")
    assert conflict["record_title"] == "Lagoon Restaurant" and conflict["field"] == "hours"
    merge = next(q for q in items if q["kind"] == "collection_merge")
    assert merge["question_tr"] == "Bu iki liste aynı şeyi mi anlatıyor?"
    assert sorted(merge["collections"]) == ["atistirmalik_items", "restaurants"]
    assert {card["title"] for card in merge["duplicate_records"]} == {"Restoranlar", "Atıştırmalık"}

    current = setup.store.read(WORKSPACE, source.id, "restaurants", mode="approved")
    assert json.loads(current)  # agreeing values are published as approved
    detail = setup.client.get(BASE + "/record-jobs/" + job["job_id"]).json()
    assert any("tablo ve listelerden" in note for note in detail["summary"]["notes"])
    assert any("about.docx" in note for note in detail["summary"]["notes"])
    metadata = setup.memory.locate(job["job_id"])["metadata"]["structure"]
    assert metadata["records_from_model"] == 0 and metadata["records_from_structure"] >= 5
    assert metadata["documents_needing_model"] == ["about"]
    assert setup.client.get(BASE + "/summary").json()["unsupported_fields"] == 0

    # "Different lists" is remembered: the next run does not ask again.
    answer = setup.client.post(BASE + f"/questions/{merge['id']}/answer", json={"same": False})
    assert answer.status_code == 200, answer.text
    assert all(q["kind"] != "collection_merge" for q in all_questions(setup))
    again, model = run(setup, start(setup, "request-2"), doclings)
    assert again["status"] == "done" and model.calls == []
    assert all(q["kind"] != "collection_merge" for q in all_questions(setup))
    newest = setup.store._source(WORKSPACE)
    assert newest.id != source.id and newest.collection_merge_decisions[0].same is False


def test_same_list_answer_joins_now_and_in_the_next_run(setup):
    doclings = use_sources(setup)
    setup.settings["enabled"] = False
    run(setup, start(setup), doclings)
    merge = next(q for q in all_questions(setup) if q["kind"] == "collection_merge")
    answer = setup.client.post(BASE + f"/questions/{merge['id']}/answer", json={"same": True})
    assert answer.status_code == 200, answer.text
    joined = setup.store._source(WORKSPACE)
    keys = [c["key"] for c in joined.workspace_schema["collections"]]
    assert keys == [merge["collections"][0]]
    assert {r.type for r in joined.records} == {merge["collections"][0]}
    job, _ = run(setup, start(setup, "request-2"), doclings)
    assert job["status"] == "done"
    rerun = setup.store._source(WORKSPACE)
    assert len(rerun.workspace_schema["collections"]) == 1  # the answer is applied at grouping
    assert all(q["kind"] != "collection_merge" for q in all_questions(setup))


def test_prose_document_uses_the_model_only_when_it_is_on(setup):
    doclings = use_sources(setup)
    job, model = run(setup, start(setup), doclings)
    assert job["status"] == "done", job
    assert model.calls  # discovery + extraction for the prose document only (asserted in fake)
    source = setup.store._source(WORKSPACE)
    assert {r.type for r in source.records} == {"restaurants", "atistirmalik_items", "policies"}
    metadata = setup.memory.locate(job["job_id"])["metadata"]["structure"]
    assert metadata["documents_for_model"] == ["about"]
    assert metadata["documents_used_model"] == ["about"]
    assert metadata["records_from_model"] == 1 and metadata["records_from_structure"] >= 5


def test_model_off_without_structure_stops_with_a_plain_note(setup):
    setup.settings["enabled"] = False
    response = setup.client.post(BASE + "/record-jobs", json={"request_id": "off"})
    assert response.status_code == 202  # karar 21: no longer a 409 when the model is off
    job, model = run(setup, response.json()["job_id"], {})
    assert job["status"] == "failed" and job["error_code"] == "needs_model"
    assert model.calls == []
    assert lifecycle.ERRORS["needs_model"].startswith("Belgelerde tablo")


# --------------------------------------------------------------------------- plan details


def test_plan_reports_coverage_and_reduced_context_for_the_model():
    contexts, doclings = sources()
    documents = [discovery_document(key, contexts[key]) for key in sorted(contexts)]
    plan = build_structure_plan(documents, doclings, WORKSPACE)
    assert plan.needs_model == ["about"]
    assert plan.documents["menu"].coverage == 1.0 and plan.documents["hours"].coverage == 1.0
    assert plan.documents["about"].docling is False
    reduced = reduced_context(contexts["menu"], plan.documents["menu"].covered)
    assert "Lagoon Restaurant" not in reduced and "## Restoranlar" in reduced
    assert "## Kaynak anahtarları" in reduced
    assert reduced_context(contexts["about"], []) == contexts["about"]
    # A remembered "same" answer joins the lists before records are built.
    signature = plan.questions[0].signatures[0]
    joined = build_structure_plan(documents, doclings, WORKSPACE, {signature: True})
    assert [c.key for c in joined.schema.collections] == ["restaurants"]
    assert joined.questions == [] and joined.answered == [signature]


def test_keys_are_english_when_obvious_and_normalized_otherwise():
    assert collection_key("Restoranlar") == "restaurants"
    assert collection_key("Toplantı Salonları") == "meeting_rooms"
    assert collection_key("Spa Treatment") == "spa_treatments"
    assert collection_key("Atıştırmalık") == "atistirmalik_items"
    assert collection_key("2026 Fiyatları") == "list_2026_fiyatlari_items"
    assert field_key("Açılış Saatleri") == "hours"
    assert field_key("Mutfak") == "mutfak"
    assert field_key("type") == "category"
    assert field_key("i18n") == "i18n_value"


# --------------------------------------------------------------------------- robustness


def test_mislabelled_header_row_is_read_as_data():
    rows = [["Lagoon Restaurant", "07:00-10:30"], ["Sunset Grill", "12:30-17:00"],
            ["Beach Bar", "10:00-24:00"]]
    (unit,) = structure_units(docling([{"$ref": "#/texts/0"}, {"$ref": "#/tables/0"}],
                                      texts=[heading(0, "Restoranlar")], tables=[table(0, rows)]), "d")
    assert unit.header_source != "column_header"
    assert [item.name for item in unit.items] == ["Lagoon Restaurant", "Sunset Grill", "Beach Bar"]
    # A real label row stays the header.
    labelled = [["Restoran", "Saat"], *rows]
    (unit,) = structure_units(docling([{"$ref": "#/tables/0"}], tables=[table(0, labelled)]), "d")
    assert unit.header_source == "column_header" and unit.fields == ["Restoran", "Saat"]
    # Every row flagged: only a first row of distinct labels is a header.
    (unit,) = structure_units(docling([{"$ref": "#/tables/0"}],
                                      tables=[table(0, labelled, header_rows=4)]), "d")
    assert unit.fields == ["Restoran", "Saat"] and len(unit.items) == 3


def test_transposed_table_is_read_by_columns():
    rows = [["", "Lagoon Restaurant", "Sunset Grill", "Beach Bar"],
            ["Açılış", "07:00", "12:30", "10:00"],
            ["Kapanış", "10:30", "17:00", "24:00"],
            ["Mutfak", "Dünya", "Izgara", "Kokteyl"]]
    (unit,) = structure_units(docling([{"$ref": "#/texts/0"}, {"$ref": "#/tables/0"}],
                                      texts=[heading(0, "Restoranlar")], tables=[table(0, rows)]), "d")
    assert unit.header_source == "transposed"
    assert [item.name for item in unit.items] == ["Lagoon Restaurant", "Sunset Grill", "Beach Bar"]
    assert unit.items[1].values == {"Açılış": "12:30", "Kapanış": "17:00", "Mutfak": "Izgara"}
    evidence = unit.items[1].evidence["Kapanış"]
    assert (evidence.row, evidence.col) == (2, 2)  # source cell, not the transposed view


def test_transposed_table_records_verify_against_the_context():
    rows = [["", "Lagoon Restaurant", "Sunset Grill"],
            ["Açılış", "07:00", "12:30"],
            ["Kapanış", "10:30", "17:00"],
            ["Mutfak", "Dünya", "Izgara"]]
    doc = docling([{"$ref": "#/texts/0"}, {"$ref": "#/tables/0"}],
                  texts=[heading(0, "Restoranlar")], tables=[table(0, rows)])
    text = context("x.docx", [("T1", "## Restoranlar"), ("T1", markdown(
        [["Restoran" if not c else c for c in rows[0]], *rows[1:]]))])
    plan = build_structure_plan([discovery_document("x", text)], {"x": doc}, WORKSPACE)
    (collection,) = plan.schema.collections
    assert collection.key == "restaurants"
    assert {f.key for f in collection.fields} == {"name", "opening_time", "closing_time", "mutfak"}
    assert plan.documents["x"].records == 2 and plan.documents["x"].rejected == {}


def numbered_lists_document():
    """Word numbered headings arrive as plain text or one-item lists; each names its own list."""
    texts = [heading(0, "Otel rehberi", label="title"),
             {"self_ref": "#/texts/1", "label": "text", "text": "3.1 Havuzlar", "children": [], "prov": []},
             *[{"self_ref": f"#/texts/{i}", "label": "list_item", "text": t, "children": [], "prov": []}
               for i, t in enumerate(["Ana havuz", "Çocuk havuzu", "Spa", "Restoranlar",
                                      "Hamam", "Sauna"], 2)]]
    groups = [
        {"self_ref": "#/groups/0", "label": "list", "name": "list",
         "children": [{"$ref": "#/texts/2"}, {"$ref": "#/texts/3"}]},
        {"self_ref": "#/groups/1", "label": "ordered_list", "name": "list",
         "children": [{"$ref": "#/texts/4"}]},
        {"self_ref": "#/groups/2", "label": "list", "name": "list",
         "children": [{"$ref": "#/texts/6"}, {"$ref": "#/texts/7"}]},
    ]
    body = [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}, {"$ref": "#/groups/0"},
            {"$ref": "#/groups/1"}, {"$ref": "#/groups/2"}]
    return docling(body, texts=texts, groups=groups)


def test_lists_take_the_nearest_numbered_heading():
    units = structure_units(numbered_lists_document(), "d")
    assert [(u.kind, u.name) for u in units] == [("list", "Havuzlar"), ("list", "Spa")]
    grouping = group_units(units)
    assert len(grouping.collections) == 2  # not one giant "Otel rehberi" collection


def test_merge_question_puts_the_larger_list_first():
    contexts, doclings = sources()
    documents = [discovery_document(key, contexts[key]) for key in sorted(contexts)]
    plan = build_structure_plan(documents, doclings, WORKSPACE)
    (question,) = plan.questions
    assert question.reason == "weak_overlap" and len(question.signatures) == 2
    assert (question.left.collection, question.left.record_count) == ("restaurants", 3)
    assert (question.right.collection, question.right.records) == (
        "atistirmalik_items", ["Pool Snack", "Kiosk"])
    assert question.left.documents == ["hours", "menu"]
