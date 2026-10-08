"""Language-neutral, offline field grounding against original source lines."""

import json
from pathlib import Path

import pytest
from docgrain_records.extractor import build_messages
from docgrain_records.models import RECORD_MODELS
from docgrain_records.runtime import RuntimeRecords
from docgrain_records.verify import _widen_quote, verify_response


def fact(value, quote, locator="§1"):
    return {"value": value, "lang": "en", "evidence": [{
        "document_id": "doc", "locator": locator, "quote": quote,
    }]}


def check(body, field, value, quote, *, locator="§1", original=None):
    kind = ("facility" if field == "hours" else "outlet" if field == "kind"
            else "activity" if field == "schedule" else "service_price" if field == "amount"
            else "room_type")
    candidate = {"type": kind, **{key: [] for key in RECORD_MODELS[kind][1].model_fields}}
    candidate["name"] = [fact("Example room", "Name: Example room")]
    candidate[field] = [fact(value, quote, locator)]
    context = "[§1 p.1]\nName: Example room\n" + body
    source = "[§1 p.1]\nName: Example room\n" + original if original is not None else None
    return verify_response(json.dumps({"records": [candidate]}), context, "doc", "en", source_context=source)


@pytest.mark.parametrize(("field", "value", "quote", "source", "expected"), [
    ("size_m2", 32, "32", "Büyüklük: 32 m2", "Büyüklük: 32 m2"),
    ("capacity", 2, "2", "Kapasite: 2 kişi", "Kapasite: 2 kişi"),
    ("size_m2", 32, "32", "Size: 32 m²", "Size: 32 m2"),
    ("capacity", 2, "2", "Kapazität: 2 Personen", "Kapazität: 2 Personen"),
    ("capacity", 2, "2", "Вместимость: 2 человека", "Вместимость: 2 человека"),
    ("size_m2", 32, "32", "32 m²", "32 m2"),
    ("size_m2", 32.5, "32,50", "Fläche: 32,50 m2", "Fläche: 32,50 m2"),
    ("hours", "08:00–20:00", "08:00–20:00", "Hours: 08:00–20:00", "Hours: 08:00–20:00"),
    ("name", "Garden room", "Garden room", "Name: Garden room", "Garden room"),
    ("view", "sea", "sea", "A sea view balcony", "sea"),
    ("features", ["balcony", "safe"], "balcony and safe", "balcony and safe", "balcony and safe"),
    ("bed_types", ["twin beds"], "twin beds", "Beds: twin beds", "twin beds"),
    ("capacity", 2, "2", "Size: 32 m2; Capacity: 2 people", "Capacity: 2 people"),
    ("schedule", "2026-10-08", "2026-10-08", "Date: 2026-10-08", "Date: 2026-10-08"),
    ("schedule", "8 Oktober 2026", "8 Oktober 2026", "Date: 8 Oktober 2026",
     "Date: 8 Oktober 2026"),
    ("amount", 40.5, "40.5", "Price: 40.5 EUR", "Price: 40.5 EUR"),
    ("amount", 40.0, "40", "€40", "€40"),
    ("amount", 40.0, "40", "40€", "40€"),
    ("kind", "restaurant", "restaurant", "Type: restaurant", "Type: restaurant"),
])
def test_bare_quotes_widen_to_the_smallest_context_span(field, value, quote, source, expected):
    result = check(source, field, value, quote)
    assert not result.rejected
    assert getattr(result.records[0], field).evidence[0].quote == expected
    assert getattr(result.records[0], field).value == value


@pytest.mark.parametrize(("field", "value", "quote", "source"), [
    ("capacity", 2, "2", "2"),
    ("capacity", 2, "(2)", "(2)"),
    ("capacity", 2, "2", "2 / 2 / 3"),
    ("capacity", 2, "2", "Capacity\n2"),
    ("hours", "08:00–20:00", "08:00–20:00", "08:00–20:00"),
    ("schedule", "2026-10-08", "2026-10-08", "2026-10-08"),
    ("amount", 40.5, "40.5", "40.5"),
    ("kind", "restaurant", "restaurant", "restaurant"),
    ("size_m2", 32, "32 m2", "32\nm2"),
])
def test_punctuation_numbers_repetitions_and_adjacent_lines_are_not_context(field, value, quote, source):
    result = check(source, field, value, quote)
    assert [(item.field, item.reason) for item in result.rejected] == [(field, "bare_value_quote")]
    assert result.rejected[0].evidence[0].quote == quote
    assert getattr(result.records[0], field) is None


@pytest.mark.parametrize(("field", "value", "quote", "source"), [
    ("capacity", 2, "Capacity: 3", "Capacity: 3"),
    ("name", "Garden room", "Name: Other room", "Name: Other room"),
    ("features", ["balcony", "safe"], "Features: balcony", "Features: balcony"),
])
def test_quote_occurrence_alone_cannot_prove_the_value(field, value, quote, source):
    assert check(source, field, value, quote).rejected[0].reason == "value_not_in_quote"


def test_part_of_a_source_word_cannot_support_free_text():
    assert check("seaside", "view", "sea", "sea").rejected[0].reason == "value_not_in_quote"


@pytest.mark.parametrize("source", ["Capacity: 132", "Capacity: 2.5", "Capacity: -2", "Capacity: 2,5"])
def test_numeric_substrings_cannot_be_repaired_into_evidence(source):
    assert check(source, "capacity", 2, "2").rejected[0].reason == "value_not_in_quote"


def test_context_word_must_be_complete_in_the_source():
    result = check("32 metre", "size_m2", 32, "32 m")
    assert result.records[0].size_m2.evidence[0].quote == "32 metre"


def test_already_labelled_quote_preserves_its_original_spelling():
    quote = "Size: ３２\u00a0m²"
    result = check(quote, "size_m2", 32, quote)
    assert result.records[0].size_m2.evidence[0].quote == quote


def test_multiline_quote_requires_value_and_context_on_one_original_line():
    quote = "Heading\nSize: 32 m2\nFooter"
    result = check(quote, "size_m2", 32, quote)
    assert result.records[0].size_m2.evidence[0].quote == quote
    assert check("Capacity\n2", "capacity", 2, "Capacity\n2").rejected[0].reason == "bare_value_quote"


def test_wrapped_unit_keeps_the_original_span_and_adds_same_line_label():
    result = check("Size: 32\nm²", "size_m2", 32, "32 m2")
    assert not result.rejected
    assert result.records[0].size_m2.evidence[0].quote == "Size: 32 m2"
    assert check("32\nm²", "size_m2", 32, "32 m2").rejected[0].reason == "bare_value_quote"


def test_widening_does_not_borrow_from_another_block_or_the_footer():
    body = "2\n[§2 p.2]\nCapacity: 2 people\n## Kaynak anahtarları\n§1 → capacity\n§2 → other"
    assert check(body, "capacity", 2, "2").rejected[0].reason == "bare_value_quote"


def test_section_projection_cannot_manufacture_context_or_repair_outside_the_section():
    assert check("Capacity: 2", "capacity", 2, "2", original="2").rejected[0].reason == "bare_value_quote"
    assert check("2", "capacity", 2, "2", original="Capacity: 2").rejected[0].reason == "bare_value_quote"
    result = check("Capacity: 2 people", "capacity", 2, "2", original="Capacity: 2 people")
    assert result.records[0].capacity.evidence[0].quote == "Capacity: 2 people"


@pytest.mark.parametrize("header", ['"column_header":"Capacity"', '"row_header":"Example room"'])
def test_bare_table_cell_retains_a_source_checked_header_locator(header):
    body = "| Name | Capacity |\n| --- | --- |\n| Example room | 2 |"
    locator = '§1 cell={"row":1,"column":2,' + header + '}'
    result = check(body, "capacity", 2, "2", locator=locator)
    assert not result.rejected
    assert result.records[0].capacity.evidence[0].quote == "2"
    assert result.records[0].capacity.evidence[0].locator == locator


@pytest.mark.parametrize("key", ["§1", "[§1 p.1]", "node_room"])
def test_value_only_column_is_supported_only_by_its_actual_header(key):
    body = "| Capacity |\n| --- |\n| 2 |\n## Kaynak anahtarları\n§1 → node_room"
    locator = key + ' cell={"row":1,"column":1,"column_header":"Capacity"}'
    result = check(body, "capacity", 2, "2", locator=locator)
    assert not result.rejected
    assert result.records[0].capacity.evidence[0].quote == "2"


def test_table_header_from_projection_must_exist_in_original_table():
    locator = '§1 cell={"row":1,"column":1,"column_header":"Capacity"}'
    result = check("| Capacity |\n| --- |\n| 2 |", "capacity", 2, "2", locator=locator,
                   original="| Size |\n| --- |\n| 2 |")
    assert result.rejected[0].reason == "bare_value_quote"


def test_all_evidence_is_checked_before_retaining_a_repair():
    candidate = {"type": "room_type", **{key: [] for key in RECORD_MODELS["room_type"][1].model_fields}}
    candidate["name"] = [fact("Example room", "Name: Example room")]
    value = fact(2, "2")
    value["evidence"].extend(fact(2, "invented")["evidence"])
    candidate["capacity"] = [value]
    raw = json.dumps({"records": [candidate]})
    result = verify_response(raw, "[§1 p.1]\nName: Example room\nCapacity: 2 people", "doc", "en")
    assert result.records[0].capacity is None
    assert result.rejected[0].reason == "quote_not_found"
    assert [e.quote for e in result.rejected[0].evidence] == ["2", "invented"]
    assert raw == json.dumps({"records": [candidate]})


@pytest.mark.parametrize("metadata", [
    '{"row":1,"column":1,"column_header":"Size"}',
    '{"row":2,"column":1,"column_header":"Capacity"}',
    '{"row":1,"column":2,"column_header":"Capacity"}',
    '{"row":1,"column":1}', '{"row":true,"column":1,"column_header":"Capacity"}',
    '{"row":1,"column":1,"column_header":"Capacity","extra":"invented"}',
    'not json', '[]',
])
def test_fabricated_table_header_or_coordinates_do_not_support_a_bare_cell(metadata):
    body = "| Capacity |\n| --- |\n| 2 |"
    assert check(body, "capacity", 2, "2", locator="§1 cell=" + metadata).rejected[0].reason == "bare_value_quote"


def test_table_without_header_locator_widens_within_the_same_row():
    body = "| Name | Capacity |\n| --- | --- |\n| Example room | 2 |"
    result = check(body, "capacity", 2, "2")
    assert result.records[0].capacity.evidence[0].quote == "room | 2"
    assert check("| Capacity |\n| --- |\n| 2 |", "capacity", 2, "2").rejected[0].reason == "bare_value_quote"


def test_standalone_names_and_descriptive_text_are_evidence():
    for source in ("Garden room", "Garden room / Garden room"):
        result = check(source, "name", "Garden room", "Garden room")
        assert len(result.records) == 1 and not result.rejected
        assert result.records[0].name.evidence[0].quote == "Garden room"
    result = check("sea view", "features", ["sea view"], "sea view")
    assert result.records[0].features.evidence[0].quote == "sea view"


def test_boolean_label_works_without_a_json_literal():
    labels = [{"lang": "en", "value": "Services"}]
    runtime = RuntimeRecords({
        "workspace_id": "example", "version": 1, "review_state": "accepted", "sources": [],
        "collections": [{
            "key": "services", "identity": "name", "label_i18n": labels,
            "description": "Example services.", "review_state": "accepted",
            "fields": [{"key": key, "type": kind, "unit": None, "label_i18n": labels,
                        "review_state": "accepted"} for key, kind in (
                            ("name", "string"), ("available", "boolean"), ("reservation", "boolean"))],
            "examples": [{"values": [{"key": "name", **fact("Example room", "Example room")}]}],
        }],
    })
    record = {"type": "services", "name": [fact("Example room", "Example room")],
              "available": [fact(True, "available")],
              "reservation": [fact(True, "Rezervasyon gerekli")]}
    context = "[§1 p.1]\nExample room\navailable\nRezervasyon gerekli"
    result = verify_response(json.dumps({"records": [record]}, ensure_ascii=False),
                             context, "doc", "tr", runtime=runtime)
    assert not result.rejected and len(result.records) == 1
    assert result.records[0].available.evidence[0].quote == "available"
    assert result.records[0].reservation.evidence[0].quote == "Rezervasyon gerekli"

    record["available"] = [fact(False, "available")]
    result = verify_response(json.dumps({"records": [record]}, ensure_ascii=False),
                             context, "doc", "tr", runtime=runtime)
    assert [(item.field, item.reason) for item in result.rejected] == [
        ("available", "value_not_in_quote")]

    record["available"] = [fact(True, "available")]
    result = verify_response(json.dumps({"records": [record]}, ensure_ascii=False),
                             context.replace("\navailable\n", "\nunavailable\n"),
                             "doc", "tr", runtime=runtime)
    assert [(item.field, item.reason) for item in result.rejected] == [
        ("available", "value_not_in_quote")]


def test_u1_fixture_repairs_and_preserves_standalone_identities():
    root = Path(__file__).parents[1] / "fixtures" / "u1-company"
    source = (root / "odalar.txt").read_text(encoding="utf-8")
    assert _widen_quote("32", source, 32) == "Büyüklük: 32 m2"
    assert _widen_quote("2", source, 2) == "Kapasite: 2 kişi"
    room = {"type": "room_type", **{key: [] for key in RECORD_MODELS["room_type"][1].model_fields}}
    room["name"] = [fact("Bahçe Odası", "Bahçe Odası")]
    room["size_m2"] = [fact(32, "32")]
    room["capacity"] = [fact(2, "2")]
    result = verify_response(json.dumps({"records": [room]}, ensure_ascii=False),
                             "[§1 p.1]\n" + source, "doc", "tr")
    assert not result.rejected and len(result.records) == 1
    assert result.records[0].name.evidence[0].quote == "Bahçe Odası"
    assert result.records[0].size_m2.evidence[0].quote == "Büyüklük: 32 m2"
    assert result.records[0].capacity.evidence[0].quote == "Kapasite: 2 kişi"
    service = (root / "hizmetler.txt").read_text(encoding="utf-8")
    assert _widen_quote("08:00–20:00", service, "08:00–20:00") == "Çalışma saatleri: 08:00–20:00"
    outlet = {"type": "outlet", **{key: [] for key in RECORD_MODELS["outlet"][1].model_fields}}
    outlet["name"] = [fact("Danışma", "Danışma")]
    outlet["hours"] = [fact("08:00–20:00", "08:00–20:00")]
    result = verify_response(json.dumps({"records": [outlet]}, ensure_ascii=False),
                             "[§1 p.1]\n" + service, "doc", "tr")
    assert not result.rejected and len(result.records) == 1
    assert result.records[0].hours.evidence[0].quote == "Çalışma saatleri: 08:00–20:00"


def test_prompt_requests_label_bearing_quotes_and_table_headers():
    prompt = build_messages("[§1 p.1]\nName: Example room", "doc", "en")[0]["content"]
    assert "SAME source line" in prompt
    assert "Names and descriptive text can quote their own" in prompt
    assert '"column_header":"Size"' in prompt
