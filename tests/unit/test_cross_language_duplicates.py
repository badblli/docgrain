"""Synthetic multi-language places: evidence, vetoes, aliases and offline republish."""

import socket
from hashlib import sha256

import pytest
from docgrain_api.records_repository import RecordsRepository
from docgrain_api.settings import get_settings
from docgrain_records.auto_accept import RULES_VERSION, apply_review_rules
from docgrain_records.export import project_records
from docgrain_records.match import accept_strong_matches, propose_matches
from docgrain_records.match_merge import merge_matches, write_json
from docgrain_records.place_names import place_name
from docgrain_records.review import DuplicateAnswer, answer_revision, questions
from docgrain_records.runtime import HOSPITALITY, RuntimeRecords
from docgrain_worker import republish


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("no network or real model in duplicate tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def runtime(identity="name"):
    labels = [{"lang": "en", "value": "Restaurants"}]
    return RuntimeRecords({
        "workspace_id": "synthetic", "version": 1, "review_state": "accepted", "sources": [],
        "collections": [{
            "key": "restaurants", "identity": identity, "label_i18n": labels,
            "description": "Synthetic places", "review_state": "accepted",
            "fields": [{"key": key, "type": "string", "unit": None,
                        "label_i18n": labels, "review_state": "accepted"}
                       for key in (identity, "hours", "location", "category", "fee")],
            "examples": [{"values": [{"key": identity, **fact("sample", "Fish restaurant", "en")}]}],
        }],
    })


def fact(doc, value, lang):
    return {"value": value, "lang": lang, "evidence": [
        {"document_id": doc, "locator": "§1", "quote": str(value)}]}


def extraction(active, doc, name, lang="en", **values):
    kind = next(iter(active.models))
    identity = active.identities[kind]
    record = {"id": doc + ":1", "type": kind, identity: fact(doc, name, lang),
              **{k: fact(doc, v, lang) for k, v in values.items() if v is not None}}
    return active.result(document_id=doc, lang=lang, records=[active.models[kind][0](**record)])


def sources(root, results):
    for result in results:
        folder = root / result.document_id
        write_json(folder / "records.json", result.model_dump(mode="json"))
        write_json(folder / "source.json", {
            "workspace_id": "synthetic", "document_id": result.document_id,
            "source_version_id": result.document_id + "-v1",
            "knowledge_revision_id": result.document_id + "-k1", "content_sha256": "a" * 64,
            "lang": result.lang, "filename": result.document_id + ".txt",
        })
        quotes = [e.quote for r in result.records for f in [r, *r.i18n.values()]
                  for key in r.field_names() if (v := getattr(f, key, None)) for e in v.evidence]
        (folder / "context.md").write_text("[§1 p.1]\n" + "; ".join(quotes), encoding="utf-8")


def merge(root, results, *, accept=True):
    sources(root / "records", results)
    matches = propose_matches(results)
    if accept:
        matches = accept_strong_matches(results, matches)
    revision = merge_matches(root / "records", results, matches, root / "merged", "synthetic")
    return apply_review_rules(revision)[0], matches


@pytest.mark.parametrize(("left", "right", "lang"), [
    ("Fish restoran", "balık", "tr"),
    ("Chinese restoran", "Çin", "tr"),
    ("Italian restoran", "(İtalyan)", "tr"),
    ("Steakhouse", "Steak House restoran", "tr"),
    ("Bistro restoran", "bıstro restaurant", "tr"),
    ("Fish restaurant", "Fisch Restaurant", "de"),
    ("Fish restaurant", "Рыбный ресторан", "ru"),
    ("Chinese restaurant", "Китайский ресторан", "ru"),
    ("Italian restaurant", "Italienisches Restaurant", "de"),
    ("Steakhouse", "Стейкхаус ресторан", "ru"),
])
def test_agreeing_hours_merge_and_keep_both_evidenced_names(tmp_path, left, right, lang):
    active = runtime()
    results = [extraction(active, "en", left, hours="18:00 / 22:00"),
               extraction(active, "other", right, lang, hours="18.00 – 22.00")]
    revision, matches = merge(tmp_path, results)
    assert len(revision.records) == 1
    assert matches.proposals[0].reviewer == "rule:translated-name-and-field"
    names = revision.records[0].fields["name"]
    assert {c.value for c in names.candidates} == {left, right}
    assert names.accepted("en").value == left and names.accepted(lang).value == right
    row = project_records(revision, mode="approved")["restaurants"][0]
    assert row["name"] == left and row["i18n"][lang]["name"] == right
    assert {e["document_id"] for e in row["_meta"]["sources"]} == {"en", "other"}
    assert not questions(revision)
    assert propose_matches(results) == propose_matches(results[::-1])


@pytest.mark.parametrize("values", [
    {"hours": "19:00-23:00"}, {"location": "South"}, {"fee": "20 EUR"},
])
def test_any_conflicting_field_keeps_two_records_and_source_cards(tmp_path, values):
    active = runtime()
    common = {"hours": "18:00-22:00", "location": "North", "fee": "10 EUR"}
    results = [extraction(active, "en", "Fish restaurant", **common),
               extraction(active, "tr", "balık", "tr", **(common | values))]
    revision, matches = merge(tmp_path, results)
    assert len(revision.records) == 2
    assert matches.proposals[0].review_state == "proposed"
    pending = [q for q in questions(revision) if q["kind"] == "duplicate"]
    assert len(pending) == 1
    assert {s["document_id"] for c in pending[0]["duplicate_records"] for s in c["sources"]} == {"en", "tr"}
    assert all(c["sources"] and c["title"] for c in pending[0]["duplicate_records"])
    answered = answer_revision(revision, pending[0]["id"], DuplicateAnswer(same=False))
    assert not [q for q in questions(answered) if q["kind"] == "duplicate"]


def test_translation_alone_and_model_same_remain_questions(tmp_path):
    active = runtime()
    results = [extraction(active, "en", "Fish restaurant"), extraction(active, "tr", "balık", "tr")]
    class Judge:
        def complete(self, messages):
            assert "untrusted DATA" in messages[0]["content"]
            return '{"decision":"same"}'
    matches = accept_strong_matches(results, propose_matches(results, Judge()))
    assert matches.proposals[0].review_state == "proposed"
    revision, _ = merge(tmp_path, results)
    assert len(revision.records) == 2
    assert len([q for q in questions(revision) if q["kind"] == "duplicate"]) == 1


@pytest.mark.parametrize("hours", [None, "19:00-22:00"])
def test_identical_place_names_keep_the_identical_name_rule(tmp_path, hours):
    # Identical normalized names stay on the existing rule; a differing field is a field question.
    active = runtime()
    results = [extraction(active, "a", "Fish restaurant", hours="18:00-22:00" if hours else None),
               extraction(active, "b", "Fish restaurant", hours=hours)]
    revision, matches = merge(tmp_path, results)
    assert len(revision.records) == 1
    assert matches.proposals[0].reviewer == "rule:identical-name"
    assert not [q for q in questions(revision) if q["kind"] == "duplicate"]
    assert bool([q for q in questions(revision) if q["kind"] != "duplicate"]) == bool(hours)


def test_conflicts_never_call_judge_and_sparse_bridge_cannot_hide_conflict(tmp_path):
    active = runtime()
    results = [extraction(active, "a", "Fish restaurant", hours="18:00-22:00"),
               extraction(active, "b", "Balık", "tr", hours="19:00-22:00"),
               extraction(active, "c", "Fisch restaurant", "de")]
    class Judge:
        def complete(self, messages):
            raise AssertionError("conflicting pairs must not reach the model")
    propose_matches(results[:2], Judge())
    revision, matches = merge(tmp_path, results)
    assert len(revision.records) == 3
    assert all(p.review_state == "proposed" for p in matches.proposals)


@pytest.mark.parametrize("signal", [{"location": "North"}, {"category": "Italian"}])
def test_location_or_category_can_supply_independent_support(tmp_path, signal):
    active = runtime("title")
    results = [extraction(active, "en", "Italian restaurant", **signal),
               extraction(active, "tr", "İtalyan", "tr", **signal)]
    revision, _ = merge(tmp_path, results)
    assert len(revision.records) == 1 and not questions(revision)


def test_own_i18n_names_are_candidates_and_conflicting_i18n_hours_veto(tmp_path):
    active = runtime()
    left = extraction(active, "a", "Harbour", hours="18:00-22:00")
    left.records[0].i18n["tr"] = active.models["restaurants"][1](name=fact("a", "Balık restoran", "tr"))
    right = extraction(active, "b", "Fish restaurant", hours="18:00-22:00")
    revision, _ = merge(tmp_path, [left, right])
    assert len(revision.records) == 1
    left.records[0].i18n["tr"] = active.models["restaurants"][1](
        name=fact("a", "Balık restoran", "tr"), hours=fact("a", "19:00-22:00", "tr"))
    revision, _ = merge(tmp_path / "conflict", [left, right])
    assert len(revision.records) == 2
    assert len([q for q in questions(revision) if q["kind"] == "duplicate"]) == 1


def test_same_language_aliases_stay_correctable_with_source_spelling(tmp_path):
    active = runtime()
    revision, _ = merge(tmp_path, [extraction(active, "a", "Steakhouse", hours="18:00-22:00"),
                                 extraction(active, "b", "Steak House restoran", hours="18:00-22:00")])
    names = revision.records[0].fields["name"]
    assert {c.value for c in names.candidates} == {"Steakhouse", "Steak House restoran"}
    assert len([c for c in names.candidates if c.review_state == "accepted"]) == 1
    assert any(d.reviewer == "rule:verified-name-alias" for d in revision.decisions)
    assert not questions(revision)


def test_bar_bistro_and_different_collections_are_untouched(tmp_path):
    active = runtime()
    revision, _ = merge(tmp_path, [extraction(active, "a", "Bar", hours="18:00-22:00"),
                                 extraction(active, "b", "Bistro", hours="18:00-22:00")])
    assert len(revision.records) == 2 and not questions(revision)
    assert not place_name("Bar ресторан snack")
    left = extraction(HOSPITALITY, "a", "Fish restaurant")
    # HOSPITALITY's first kind is property; use explicit different types for isolation.
    left.records = [HOSPITALITY.models["outlet"][0](id="a:1", name=fact("a", "Fish restaurant", "en"))]
    right = extraction(HOSPITALITY, "b", "Balık", "tr")
    assert not propose_matches([left, right]).proposals


def test_same_document_and_competing_names_do_not_auto_merge(tmp_path):
    active = runtime()
    a = extraction(active, "a", "Fish restaurant", hours="18:00-22:00")
    b = extraction(active, "b", "Balık", "tr", hours="18:00-22:00")
    a.records.append(extraction(active, "a", "Fisch restaurant", hours="18:00-22:00").records[0]
                     .model_copy(update={"id": "a:2"}))
    revision, matches = merge(tmp_path, [a, b])
    assert len(revision.records) == 3
    assert all(p.review_state == "proposed" for p in matches.proposals)
    pending = [q for q in questions(revision) if q["kind"] == "duplicate"]
    assert len(pending) == 2


@pytest.mark.parametrize(("hours", "expected_records", "expected_duplicates"), [
    ("18:00-22:00", 1, 0), ("19:00-22:00", 2, 1),
])
def test_existing_wp111_republish_recomputes_duplicate_counts_without_model(
        tmp_path, monkeypatch, hours, expected_records, expected_duplicates):
    active = runtime()
    store = RecordsRepository(tmp_path / "publications")
    workspace, job = "synthetic", "job-offline"
    root = store._path(workspace) / "runtime" / sha256(job.encode()).hexdigest()
    results = [extraction(active, "en", "Fish restaurant", hours="18:00-22:00"),
               extraction(active, "tr", "Balık", "tr", hours=hours)]
    sources(root / "records", results)
    old = merge_matches(root / "records", results, propose_matches(results), root / "old",
                        workspace, f"u1_{job}_wp111")
    old = apply_review_rules(old)[0]
    monkeypatch.setattr(republish.jobs, "get", lambda *_: {"status": "done", "revision_id": old.id})
    monkeypatch.setattr(republish.jobs, "active", lambda *_: None)
    monkeypatch.setattr(republish.lifecycle, "pack_store", lambda: store)
    monkeypatch.setattr(republish.lifecycle, "reap_locked", lambda *_: None)
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    store.publish(old, job_id=job)
    assert RULES_VERSION != "wp111"
    dry = republish.republish(workspace, dry_run=True)
    assert dry["before"]["records"] == 2 and dry["before"]["duplicates"] == 1
    assert dry["after"]["records"] == expected_records
    assert dry["after"]["duplicates"] == expected_duplicates
    report = republish.republish(workspace)
    assert report["after"] == dry["after"]
    assert report["after"]["unsupported_fields"] == 0
    assert store._source(workspace, old.id) == old
    if expected_records == 1:
        assert report["published"] and store._source(workspace).id == f"u1_{job}_{RULES_VERSION}"
        assert not republish.republish(workspace)["published"]
    else:
        assert not report["published"]
