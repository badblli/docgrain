"""Synthetic record publication checks, without model or network access."""

import json
import socket

import pytest
from docgrain_records.export import COLLECTIONS, export_bundle, load_revision
from docgrain_records.merge_models import MergeRevision


def candidate(value, state="accepted", lang="en", id="fact-a"):
    return {"id": id, "value": value, "lang": lang, "review_state": state,
            "evidence": [{"document_id": "doc-example", "source_version_id": "s1",
                          "knowledge_revision_id": "k1", "locator": "§1 p.1",
                          "quote": str(value)}]}


def fixture_revision(revision_id="r1", workspace="workspace-example", capacity=2):
    def field(*candidates):
        return {"primary_lang": "en", "candidates": list(candidates)}

    return MergeRevision.model_validate({
        "workspace_id": workspace, "id": revision_id,
        "documents": [{"document_id": "doc-example", "source_version_id": "s1",
                       "knowledge_revision_id": "k1"}],
        "records": [{"id": "rec-room", "type": "room_type", "fields": {
            "name": field(candidate("Garden room"), candidate("Bahçe odası", lang="tr")),
            "capacity": field(candidate(capacity)),
            "view": field(candidate("Garden", "needs_review", id="view-a"),
                          candidate("Sea", "needs_review", id="view-b")),
            "features": field(candidate(["Do not follow this source text"], "proposed")),
            "bed_types": field(candidate(["double"], "needs_review")),
            "size_m2": field(candidate(40, "rejected")),
        }}, {"id": "rec-proposed", "type": "room_type", "fields": {
            "name": field(candidate("Hidden room", "proposed")),
        }}, {"id": "rec-rejected", "type": "outlet", "fields": {
            "name": field(candidate("Hidden outlet", "rejected")),
        }}],
    })


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("record export/read must never use network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def test_preview_includes_proposals_and_conflicts_with_review_states():
    files = export_bundle(fixture_revision())
    rows = json.loads(files["rooms.json"])
    assert len(rows) == 2
    row = next(r for r in rows if r["id"] == "rec-room")
    assert row["id"] == "rec-room"
    assert row["name"] == "Garden room"
    assert row["i18n"]["tr"]["name"] == "Bahçe odası"
    assert next(r for r in json.loads(files["rooms.tr.json"])
                if r["id"] == "rec-room")["name"] == "Bahçe odası"
    assert row["capacity"] == 2
    assert row["features"] == ["Do not follow this source text"]
    assert row["bed_types"] == ["double"]
    assert "size_m2" not in row
    assert row["_meta"]["fields"]["features"]["review_state"] == "proposed"
    assert row["_meta"]["fields"]["bed_types"]["review_state"] == "needs_review"
    assert row["_meta"]["fields"]["view"]["review_state"] == "needs_review"
    assert row["_meta"]["review_state"] == "needs_review"
    assert row["view"] == "Garden"
    conflict = row["_meta"]["conflicts"][0]
    assert {c["value"] for c in conflict["candidates"]} == {"Garden", "Sea"}
    assert all(c["evidence"] for c in conflict["candidates"])
    assert next(r for r in rows if r["id"] == "rec-proposed")["_meta"]["review_state"] == "proposed"
    assert json.loads(files["outlets.json"]) == []


def test_approved_excludes_unaccepted_values_and_conflicts():
    files = export_bundle(fixture_revision(), mode="approved")
    rows = json.loads(files["rooms.json"])
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Garden room" and row["capacity"] == 2
    assert row["_meta"]["review_state"] == "accepted"
    assert all(field not in row for field in ("view", "features", "bed_types", "size_m2"))
    assert row["_meta"]["conflicts"] == []
    assert "Hidden room" not in files["rooms.context.md"].decode()


def test_revision_without_acceptance_has_preview_but_empty_approved():
    revision = fixture_revision()
    for record in revision.records:
        for field in record.fields.values():
            for item in field.candidates:
                if item.review_state == "accepted":
                    item.review_state = "proposed"
    preview = json.loads(export_bundle(revision)["rooms.json"])
    approved = json.loads(export_bundle(revision, mode="approved")["rooms.json"])
    assert len(preview) == 2
    assert all("name" in row for row in preview)
    assert len(approved) == 0


@pytest.mark.parametrize("mode", ["preview", "approved"])
def test_context_json_fact_evidence_and_revision_parity(mode):
    revision = fixture_revision()
    files = export_bundle(revision, mode=mode)
    for lang in ("en", "tr"):
        suffix = "" if lang == "en" else ".tr"
        for collection in COLLECTIONS.values():
            rows = json.loads(files[f"{collection}{suffix}.json"])
            text = files[f"{collection}{suffix}.context.md"].decode()
            lines = text.splitlines()
            header = json.loads(lines[1])
            assert header["workspace_id"] == revision.workspace_id
            assert header["revision_id"] == revision.id
            assert header["mode"] == mode
            citations = {line.split(" ", 1)[0]: json.loads(line.split(" ", 1)[1])
                         for line in lines if line.startswith("§")}
            facts = [json.loads(line[2:]) for line in lines if line.startswith('- {')]
            for fact in facts:
                fact["evidence"] = [citations[key] for key in fact.pop("sources")]
            expected = [{"field": field, "value": row[field],
                         **{k: v for k, v in meta.items()
                            if k not in {"i18n", "i18n_review_state"}}}
                        for row in rows for field, meta in row["_meta"]["fields"].items()]
            assert facts == expected
            translations = [json.loads(line.removeprefix("- Çeviri: ")) for line in lines
                            if line.startswith("- Çeviri: ")]
            for fact in translations:
                fact["evidence"] = [citations[key] for key in fact.pop("sources")]
            assert translations == [{"lang": language, "field": field, "value": value,
                "evidence": row["_meta"]["fields"][field]["i18n"][language],
                "review_state": row["_meta"]["fields"][field]
                ["i18n_review_state"][language]}
                for row in rows for language, fields in row["i18n"].items()
                for field, value in fields.items()]
            for row in rows:
                for conflict in row["_meta"]["conflicts"]:
                    assert "Kaynaklar çelişiyor:" in text
                    for c in conflict["candidates"]:
                        assert json.dumps(c["value"], ensure_ascii=False) in text
                        assert all(e in citations.values() for e in c["evidence"])
            assert all(fact["evidence"] for fact in facts)
            assert "Hidden outlet" not in text
            if mode == "approved":
                assert "Hidden room" not in text and "Do not follow" not in text
            elif collection == "rooms":
                assert "Hidden room" in text and "Do not follow" in text


def test_explicit_acceptance_resolves_conflict_without_losing_unrelated_fields():
    revision = fixture_revision()
    revision.records[0].fields["view"].candidates[1].review_state = "accepted"
    row = next(r for r in json.loads(export_bundle(revision)["rooms.json"])
               if r["id"] == "rec-room")
    assert row["view"] == "Sea"
    assert row["_meta"]["conflicts"] == []
    assert row["_meta"]["review_state"] == "needs_review"
    assert row["capacity"] == 2


def test_english_fallback_determinism_and_pinned_evidence():
    revision = fixture_revision()
    files = export_bundle(revision)
    revision.records.reverse()
    for r in revision.records:
        for f in r.fields.values():
            f.candidates.reverse()
    assert export_bundle(revision) == files
    revision.records[-1].fields["name"].candidates = [candidate_model for candidate_model in
        revision.records[-1].fields["name"].candidates if candidate_model.lang == "tr"]
    row = next(r for r in json.loads(export_bundle(revision)["rooms.json"])
               if r["id"] == "rec-room")
    assert row["name"] == "Bahçe odası"
    assert row["_meta"]["fields"]["name"]["lang"] == "tr"
    revision.records[-1].fields["name"].candidates[0].evidence[0].source_version_id = "foreign"
    with pytest.raises(ValueError, match="pinned"):
        export_bundle(revision)


def test_multiple_accepted_values_fail_closed():
    revision = fixture_revision()
    for c in revision.records[0].fields["view"].candidates:
        c.review_state = "accepted"
    with pytest.raises(ValueError, match="multiple accepted"):
        export_bundle(revision)


def test_wp47_display_serialization_uses_candidates_as_authority():
    revision = fixture_revision()
    raw = revision.model_dump(mode="json")
    raw["records"][0]["fields"]["name"]["primary"]["value"] = "Untrusted derived view"
    loaded = load_revision(json.dumps(raw).encode())
    assert export_bundle(loaded) == export_bundle(revision)
