"""WP122: bounded comparison vocabulary over synthetic Docling exports; no network/model."""

import json
import random
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
import test_u1_pipeline
from docgrain_records.discovery_models import DiscoveryDocument
from docgrain_records.structure_records import (
    COLLECTION_KEYS,
    FIELD_KEYS,
    build_structure_plan,
    collection_key,
    field_key,
    pair_signature,
    unit_signature,
)
from docgrain_records.structure_units import group_units, norm, structure_units
from docgrain_records.structure_vocab import known_collection_key
from test_structure_first import (
    all_questions,
    context,
    docling,
    heading,
    markdown,
    run,
    table,
)
from test_u1_pipeline import BASE, WORKSPACE, start

setup = test_u1_pipeline.setup


def source(key, title, rows, lang):
    document = docling([{"$ref": "#/texts/0"}, {"$ref": "#/tables/0"}],
                       texts=[heading(0, title)], tables=[table(0, rows)])
    text = context(key + ".md", [("1", "## " + title), ("1", markdown(rows))])
    discovery = DiscoveryDocument(source={
        "document_id": key, "workspace_id": WORKSPACE, "knowledge_revision_id": key + "-k1",
        "source_version_id": key + "-s1", "content_sha256": "a" * 64, "lang": lang,
        "filename": key + ".md",
    }, context=text)
    return discovery, document


def tr_source():
    return source("tr", "Restoranlar", [["Restoran", "Açılış saatleri", "Mutfak"],
                                       ["Balık restoran", "18:00-23:00", "Deniz ürünleri"]], "tr")


def en_source(title="A la carte restaurants", hours="18:00-23:00", identity="Restaurant"):
    return source("en", title, [[identity, "Opening hours"], ["Fish restaurant", hours]], "en")


def plan_for(*sources, decisions=None):
    return build_structure_plan([doc for doc, _ in sources],
                                {doc.source.document_id: raw for doc, raw in sources},
                                WORKSPACE, decisions)


def use_sources(setup, *sources):
    setup.settings["enabled"] = False
    setup.docs[:] = [doc for doc, _ in sources]
    setup.metadata_docs[:] = [SimpleNamespace(id=doc.source.document_id, workspace_id=WORKSPACE,
                                              latest_version_id=doc.source.document_id + "-v1")
                              for doc, _ in sources]
    for doc, _ in sources:
        key = doc.source.document_id
        setup.versions[key] = SimpleNamespace(id=key + "-v1", status="done", workspace_id=WORKSPACE,
                                              content_sha256="a" * 64)
        setup.preparations[key + "-v1"] = SimpleNamespace(status="done", page_failures=[])
    return {doc.source.document_id: raw for doc, raw in sources}


def test_tr_en_join_without_question_or_split_hours_and_keep_source_spelling():
    sources = (tr_source(), en_source())
    before = deepcopy(sources)
    plan = plan_for(*sources)
    (collection,) = plan.schema.collections
    assert collection.key == "restaurants" and plan.questions == []
    assert [f.key for f in collection.fields] == ["name", "hours", "mutfak"]
    assert all(doc.records == 1 and doc.rejected == {} for doc in plan.documents.values())
    assert plan.candidates["tr"]["records"][0]["name"][0]["value"] == "Balık restoran"
    assert plan.candidates["en"]["records"][0]["name"][0]["value"] == "Fish restaurant"
    assert sources == before


def test_de_ru_join_the_same_collection_with_one_hours_key():
    de = source("de", "Restaurants", [["Restaurant", "Öffnungszeiten"],
                                     ["Fisch Restaurant", "18:00-23:00"]], "de")
    ru = source("ru", "Рестораны", [["Ресторан", "Часы работы"],
                                   ["Рыбный ресторан", "18:00-23:00"]], "ru")
    plan = plan_for(tr_source(), en_source(), de, ru)
    (collection,) = plan.schema.collections
    assert collection.key == "restaurants" and plan.questions == []
    assert [f.key for f in collection.fields] == ["name", "hours", "mutfak"]
    assert set(plan.candidates) == {"tr", "en", "de", "ru"}
    assert all(doc.records == 1 and doc.rejected == {} for doc in plan.documents.values())
    assert field_key("Часы работы") == "hours"
    assert collection_key("Рестораны") == "restaurants"


@pytest.mark.parametrize(("label", "key"), [
    ("Öffnungszeiten", "hours"), ("Часы работы", "hours"), ("Preis", "price"),
    ("Цена", "price"), ("Kapazität", "capacity"), ("Вместимость", "capacity"),
    ("Mutfak", "mutfak"), ("Cuisine", "cuisine"), ("Opening hours", "hours"),
    ("Условия", "usloviya"), ("2026 Условия", "field_2026_usloviya"),
    ("i18n", "i18n_value"),
])
def test_bounded_fields_and_ascii_fallback(label, key):
    assert field_key(label) == key


@pytest.mark.parametrize(("title", "key"), [
    ("A la carte restaurants", "restaurants"), ("Ana restoranlar", "restaurants"),
    ("Unsere Restaurants", "restaurants"), ("Рестораны", "restaurants"),
    ("ресторан", "restaurants"), ("Bars", "bars"), ("Бары", "bars"),
    ("Zimmer", "rooms"), ("Номера", "rooms"), ("meeting_rooms", "meeting_rooms"),
    ("Unsere meeting rooms", "meeting_rooms"), ("Toplantı salonları", "meeting_rooms"),
    ("Restaurants & Bars", None), ("Бары и Рестораны", None), ("Rooms / Meeting rooms", None),
    ("Restaurants overview", None), ("Our venues", None), ("Counterbars", None),
])
def test_known_head_noun_and_mixed_kind_abstention(title, key):
    assert known_collection_key(title) == key
    if key:
        assert collection_key(title) == key


def test_unknown_russian_keys_compile_in_the_runtime():
    ru = source("ru", "Условия", [["Название", "Услуга"], ["Доставка", "Бесплатно"]], "ru")
    plan = plan_for(ru)
    (collection,) = plan.schema.collections
    assert collection.key == "usloviya_items"
    assert [f.key for f in collection.fields] == ["name", "usluga"]
    # build_structure_plan has already compiled and verified using RuntimeRecords.
    assert plan.documents["ru"].records == 1 and plan.documents["ru"].rejected == {}


def test_different_known_kinds_never_join_or_ask_even_with_shared_items():
    bars = source("tr", "Barlar", [["Bar", "Açılış saatleri"],
                                  ["Fish restaurant", "18:00-23:00"]], "tr")
    plan = plan_for(bars, en_source())
    assert {c.key for c in plan.schema.collections} == {"bars", "restaurants"}
    assert plan.questions == []


def test_same_known_kind_with_weak_fields_asks_instead_of_title_only_join():
    left = source("a", "Restoranlar", [["Restoran", "Saat", "Mutfak"],
                                      ["Orman", "12:00", "Izgara"]], "tr")
    right = source("b", "Restaurants", [["Restaurant", "Opening hours", "Price"],
                                        ["Garden", "13:00", "30"]], "en")
    plan = plan_for(left, right)
    assert len(plan.schema.collections) == 2
    (question,) = plan.questions
    assert question.reason == "weak_overlap"


def test_translated_item_overlap_can_join_known_kind_with_disjoint_value_fields():
    left = source("tr", "Restoranlar", [["Restoran", "Mutfak"],
                                       ["Balık restoran", "Deniz ürünleri"]], "tr")
    right = source("en", "Restaurants", [["Restaurant", "Price"],
                                         ["Fish restaurant", "50"]], "en")
    plan = plan_for(left, right)
    assert [c.key for c in plan.schema.collections] == ["restaurants"]
    assert plan.questions == []


def test_identical_headers_alone_do_not_establish_an_unknown_collection_kind():
    left = source("a", "Our venues", [["Name", "Hours"], ["Garden", "12:00"]], "en")
    right = source("b", "Restaurants", [["Name", "Hours"], ["Forest", "13:00"]], "en")
    plan = plan_for(left, right)
    assert len(plan.schema.collections) == 2
    (question,) = plan.questions
    assert question.reason == "weak_overlap"


def test_signatures_still_hash_raw_labels_and_grouping_is_order_independent():
    units = [unit for doc, raw in (tr_source(), en_source())
             for unit in structure_units(raw, doc.source.document_id)]
    original = []
    for unit in units:
        payload = [unit.document_id, unit.kind, norm(unit.name),
                   sorted({norm(label) for label in unit.fields} - {""})]
        digest = sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]
        assert unit_signature(unit) == digest
        original.append(digest)
    expected = "cm_" + sha256("\n".join(sorted(original)).encode()).hexdigest()[:24]
    assert pair_signature(*units) == expected
    first = group_units(units).to_dict()
    random.Random(122).shuffle(units)
    assert group_units(units).to_dict() == first
    assert FIELD_KEYS["acilis saatleri"] == "hours"
    assert COLLECTION_KEYS["restoranlar"] == "restaurants"


@pytest.mark.parametrize("same", [True, False])
def test_unknown_kind_asks_once_and_answer_applies_now_and_next_run(setup, same):
    doclings = use_sources(setup, tr_source(), en_source("Our venues", identity="Venue"))
    job, model = run(setup, start(setup), doclings)
    assert job["status"] == "done" and model.calls == []
    (question,) = [q for q in all_questions(setup) if q["kind"] == "collection_merge"]
    assert question["question_tr"] == "Bu iki liste aynı şeyi mi anlatıyor?"
    assert question["reason"] == "weak_overlap"
    answer = setup.client.post(BASE + f"/questions/{question['id']}/answer", json={"same": same})
    assert answer.status_code == 200, answer.text
    current = setup.store._source(WORKSPACE)
    assert len(current.workspace_schema["collections"]) == (1 if same else 2)
    assert all(q["kind"] != "collection_merge" for q in all_questions(setup))
    job, model = run(setup, start(setup, "next-run"), doclings)
    assert job["status"] == "done" and model.calls == []
    current = setup.store._source(WORKSPACE)
    assert len(current.workspace_schema["collections"]) == (1 if same else 2)
    assert all(q["kind"] != "collection_merge" for q in all_questions(setup))
    assert current.collection_merge_decisions[-1].same is same


@pytest.mark.parametrize("hours", ["18:00-23:00", "19:00-23:00"])
def test_pipeline_join_exposes_translated_places_to_wp115(setup, hours):
    doclings = use_sources(setup, tr_source(), en_source(hours=hours))
    job, model = run(setup, start(setup), doclings)
    assert job["status"] == "done", job
    assert model.calls == []
    revision = setup.store._source(WORKSPACE)
    assert [c["key"] for c in revision.workspace_schema["collections"]] == ["restaurants"]
    questions = all_questions(setup)
    if hours == "18:00-23:00":
        assert questions == []
        (record,) = revision.records
        evidence = [e for f in record.fields.values() for c in f.candidates for e in c.evidence]
        assert {e.document_id for e in evidence} == {"tr", "en"}
        assert {c.value for c in record.fields["name"].candidates} == {
            "Balık restoran", "Fish restaurant"}
    else:
        assert len(revision.records) == 2
        (question,) = questions
        assert question["kind"] == "duplicate"
        assert set(question["record_ids"]) == {r.id for r in revision.records}
    assert setup.client.get(BASE + "/summary").json()["unsupported_fields"] == 0
