"""Synthetic recall measurements, gap-filling passes and bounded/offline discovery."""

import json
from pathlib import Path

import pytest
from docgrain_records.discovery import (
    build_discovery_messages,
    discover,
    discovery_batches,
    prompt_size,
    verify_discovery,
)
from docgrain_records.discovery_models import DiscoveryDocument
from docgrain_records.discovery_signals import content_blocks, detect_signals
from docgrain_records.extractor import _blocks, normalize_quote

FIXTURES = Path(__file__).parents[1] / "fixtures" / "collections"
HOTEL_ITEMS = {
    "§1": ("rooms", "Garden Room"),
    "§2": ("restaurants", "Orchard Restaurant"),
    "§3": ("bars", "Lobby Bar"),
    "§4": ("activities", "Yoga"),
    "§5": ("facilities", "Indoor Pool"),
    "§6": ("policies", "Check-in begins at 14:00."),
    "§7": ("contacts", "Reception"),
    "§8": ("service_prices", "Laundry"),
}


def document(context=None, document_id="hotel-example"):
    return DiscoveryDocument(source={
        "document_id": document_id, "workspace_id": "workspace-example",
        "knowledge_revision_id": "revision-example", "source_version_id": "source-example",
        "content_sha256": "a" * 64, "lang": "en",
    }, context=context or (FIXTURES / "plain_text_hotel.context.md").read_text(encoding="utf-8"))


def proposal(block, key, name, fields=None, values=None):
    return {"key": key, "label_i18n": [{"lang": "en", "value": key}],
            "description": "Items explicitly listed in the source.",
            "fields": fields or [{"key": "name", "type": "string", "unit": None,
                                   "label_i18n": [{"lang": "en", "value": "Name"}]}],
            "examples": [{"values": values or [{
                "key": "name", "value": name, "lang": "en", "evidence": [{
                    "document_id": block["document_id"], "locator": block["locator"],
                    "quote": name,
                }],
            }]}]}


class SectionModel:
    def __init__(self, miss_first=False):
        self.calls = []
        self.miss_first = miss_first

    def complete(self, messages, schema):
        payload = json.loads(messages[1]["content"])
        self.calls.append(messages)
        collections = []
        for block in payload["untrusted_source_blocks"]:
            if self.miss_first and payload["round"] == 1 and block["locator"] != "§1":
                continue
            key, name = HOTEL_ITEMS[block["locator"]]
            if name in block["text"]:
                collections.append(proposal(block, key, name))
        return json.dumps({"collections": collections})


def test_plain_text_hotel_discovers_all_eight_lists_with_section_model():
    docs, model = [document()], SectionModel()
    result = discover(docs, "workspace-example", model)
    assert {collection.key for collection in result.collections} == {
        key for key, _ in HOTEL_ITEMS.values()
    }
    assert len(result.collections) >= 6 and not result.rejected
    assert len(model.calls) == 1 and result.coverage == 1 and result.uncovered == []
    assert result.model_dump()["coverage"] == 1
    for collection in result.collections:
        for example in collection.examples:
            for value in example.values:
                for evidence in value.evidence:
                    assert normalize_quote(evidence.quote) in _blocks(docs[0].context)[evidence.locator]


def test_coverage_loop_second_round_only_receives_and_fills_missing_sections():
    model = SectionModel(miss_first=True)
    result = discover([document()], "workspace-example", model)
    assert len(model.calls) == 2 and len(result.collections) == 8
    first, second = [json.loads(call[1]["content"]) for call in model.calls]
    assert len(first["untrusted_source_blocks"]) == 8
    assert {block["locator"] for block in second["untrusted_source_blocks"]} == {
        f"§{index}" for index in range(2, 9)
    }
    assert second["round"] == 2
    assert second["proposed_collections"][0]["key"] == "rooms"
    assert "Garden Room" not in model.calls[1][1]["content"]
    assert not result.rejected and result.coverage == 1 and not result.uncovered


@pytest.mark.parametrize("fixture,kinds", [
    ("hospitality.context.md", {"table", "heading", "section_text"}),
    ("plain_text_hotel.context.md", {"heading", "list", "fields", "section_text"}),
    ("ocr_like_hotel.context.md", {"heading", "section_text", "measure"}),
])
def test_all_source_formats_have_locatable_section_signals(fixture, kinds):
    doc = document((FIXTURES / fixture).read_text(encoding="utf-8"))
    signals = detect_signals([doc])
    assert kinds <= {signal["kind"] for signal in signals}
    assert {sample["locator"] for signal in signals if signal["kind"] == "section_text"
            for sample in signal["samples"]} == {block["locator"] for block in content_blocks([doc])}
    for signal in signals:
        for sample in signal["samples"]:
            assert normalize_quote(sample["quote"]) in _blocks(doc.context)[sample["locator"]]


def test_coverage_is_character_weighted_document_specific_and_resolves_aliases():
    docs = [document(), document(document_id="second-example")]
    block = content_blocks(docs)[0]
    candidate = proposal(block, "rooms", "Garden Room")
    candidate["examples"][0]["values"][0]["evidence"][0]["locator"] = "hotel_rooms"
    result = verify_discovery(json.dumps({"collections": [candidate]}), docs, "workspace-example")
    all_blocks = content_blocks(docs)
    assert result.coverage == len(block["text"]) / sum(len(item["text"]) for item in all_blocks)
    assert "ROOMS" in result.uncovered  # The other document's identically numbered block is missing.
    assert "Restaurants" in result.uncovered and not result.rejected
    candidate["examples"][0]["values"][0]["evidence"][0]["quote"] = "Invented room"
    rejected = verify_discovery(json.dumps({"collections": [candidate]}), docs, "workspace-example")
    assert rejected.coverage == 0 and len(rejected.uncovered) == 8


def test_prose_and_ocr_are_sent_even_without_repeated_structures():
    text = "[§1 p.1]\nOverview\nAlpha service operates daily. Beta service operates on request.\n"
    doc = document(text)
    payload = json.loads(build_discovery_messages([doc], "workspace-example")[1]["content"])
    assert payload["untrusted_source_blocks"][0]["text"] == content_blocks([doc])[0]["text"]
    assert "Alpha service" in payload["untrusted_source_blocks"][0]["text"]


def test_repeated_single_label_lines_are_signals_without_multifield_cards():
    doc = document("[§1 p.1]\nName: Alpha\nName: Beta\n")
    signals = detect_signals([doc])
    signal = next(signal for signal in signals if signal["kind"] == "label_value")
    assert signal["pattern"] == "name" and signal["count"] == 2
    assert [sample["quote"] for sample in signal["samples"]] == ["Name: Alpha", "Name: Beta"]


def test_prompts_split_large_blocks_and_scan_late_documents_without_losing_characters():
    docs = [document("[§1 p.1]\nOverview\n" + "A service is available on request.\n" * 800),
            document(document_id="last-example")]
    batches = discovery_batches(docs, "workspace-example", max_prompt_chars=10000)
    assert len(batches) >= 3 and all(prompt_size(batch) <= 10000 for batch in batches)
    reconstructed = {}
    for batch in batches:
        for block in json.loads(batch[1]["content"])["untrusted_source_blocks"]:
            key = block["document_id"], block["locator"]
            reconstructed[key] = reconstructed.get(key, "") + block["text"]
    assert reconstructed == {(block["document_id"], block["locator"]): block["text"]
                             for block in content_blocks(docs)}


def test_all_rounds_and_model_calls_are_bounded_and_residual_gaps_are_reported():
    model = SectionModel(miss_first=True)
    docs = [document(), document(document_id="second-example")]
    result = discover(docs, "workspace-example", model, max_prompt_chars=10000)
    assert result.coverage == 1 and len(result.collections) == 8
    assert all(prompt_size(call) <= 10000 for call in model.calls)
    assert {json.loads(call[1]["content"])["round"] for call in model.calls} == {1, 2}

    class EmptyModel:
        calls = 0

        def complete(self, messages, schema):
            self.calls += 1
            return '{"collections": []}'

    empty = EmptyModel()
    result = discover([document()], "workspace-example", empty)
    assert empty.calls == 3 and result.coverage == 0 and len(result.uncovered) == 8
    assert discover([document()], "workspace-example").uncovered == result.uncovered
    before = empty.calls
    with pytest.raises(ValueError, match="max-prompt-chars"):
        discover([document()], "workspace-example", empty, max_prompt_chars=1)
    assert empty.calls == before


def test_model_cannot_cover_an_unseen_block_or_quote_unseen_continuation_text():
    docs = [document("[§1 p.1]\nRooms\nGarden Room\n" + "Long room description. " * 800 +
                     "\nFamily Room\n[§2 p.2]\nRestaurants\nOrchard Restaurant\n")]

    class UnseenQuoteModel:
        def complete(self, messages, schema):
            supplied = json.loads(messages[1]["content"])["untrusted_source_blocks"]
            if "Family Room" not in supplied[0]["text"]:
                return json.dumps({"collections": [proposal(supplied[0], "rooms", "Family Room")]})
            return '{"collections": []}'

    result = discover(docs, "workspace-example", UnseenQuoteModel(),
                      max_prompt_chars=10000, max_rounds=1)
    assert not result.collections and result.coverage == 0
    assert result.rejected and {item.reason for item in result.rejected} == {"quote_not_found"}


def test_later_pass_merges_fields_and_preserves_conflicting_definitions():
    doc = document("[§1 p.1]\nServices\nConsultation costs 40 EUR.\n"
                   "[§2 p.2]\nMore services\nScreening costs 70 EUR and lasts 30 minutes.\n" +
                   "Please book through reception. " * 6)

    class ConflictingModel:
        def complete(self, messages, schema):
            payload = json.loads(messages[1]["content"])
            block = payload["untrusted_source_blocks"][0]
            later = payload["round"] == 2
            name = "Screening" if later else "Consultation"
            candidate = proposal(block, "services", name)
            candidate["fields"].append({"key": "price", "type": "string" if later else "number",
                                        "unit": "EUR", "label_i18n": [{"lang": "en", "value": "Price"}]})
            candidate["examples"][0]["values"].append({
                "key": "price", "value": "70 EUR" if later else 40, "lang": "en", "evidence": [{
                    "document_id": block["document_id"], "locator": block["locator"],
                    "quote": "70 EUR" if later else "40 EUR",
                }],
            })
            if later:
                candidate["fields"].append({"key": "duration", "type": "integer", "unit": "minutes",
                                           "label_i18n": [{"lang": "en", "value": "Duration"}]})
                candidate["examples"][0]["values"].append({
                    "key": "duration", "value": 30, "lang": "en", "evidence": [{
                        "document_id": block["document_id"], "locator": block["locator"],
                        "quote": "30 minutes",
                    }],
                })
            return json.dumps({"collections": [candidate]})

    result = discover([doc], "workspace-example", ConflictingModel())
    assert result.coverage == 1 and not result.rejected and len(result.collections) == 1
    collection = result.collections[0]
    assert {field.key for field in collection.fields} == {"name", "price", "duration"}
    price = next(field for field in collection.fields if field.key == "price")
    assert collection.review_state == price.review_state == "needs_review"
    assert price.type == "number" and price.alternatives[0].type == "string"
