"""WP112: list questions and question time limits, with fake models and transports only."""

import importlib.util
import json
from pathlib import Path

import docgrain_access.ask as ask_module
import httpx
import pytest
import test_u1_try
from docgrain_access.ask import (
    AskResult,
    ModelTimeout,
    ModelUnavailable,
    OpenAICompatibleClient,
    ask_result,
)
from docgrain_api import try_ai
from docgrain_api.ai_access import AIAccess, ToolInvalid
from docgrain_api.records_repository import RecordsRepository
from docgrain_api.settings import get_settings
from docgrain_records.merge_models import MergedRecord
from test_ai_clients import FakeModel, invocation
from test_records_export import candidate
from test_u1_try import PATH, room_revision

setup = test_u1_try.setup

spec = importlib.util.spec_from_file_location("dene_abstain_lists", Path("benchmarks/dene_abstain.py"))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)

QUESTION = "Hangi odalar var, kaç kişilik?"
LIST_CALL = invocation("list_collection", {"collection": "rooms", "fields": ["capacity"]})


def room(record_id, name, turkish, capacity):
    def field(*candidates):
        return {"primary_lang": "en", "candidates": list(candidates)}

    return MergedRecord.model_validate({"id": record_id, "type": "room_type", "fields": {
        "name": field(candidate(name, id=record_id + "-name"),
                      candidate(turkish, lang="tr", id=record_id + "-tr")),
        "capacity": field(candidate(capacity, id=record_id + "-capacity")),
    }})


def rooms_revision(revision_id="r1"):
    revision = room_revision(revision_id)
    revision.records += [room("rec-sea", "Sea room", "Deniz Odası", 3),
                         room("rec-family", "Family suite", "Aile Süiti", 4)]
    return revision


@pytest.fixture
def access(tmp_path):
    store = RecordsRepository(tmp_path)
    store.publish(rooms_revision())
    return AIAccess(store, "workspace-example")


def listing(access, **arguments):
    return access.call("list_collection", {"collection": "rooms", "fields": ["capacity"]} | arguments)


def ids(access):
    """Source ids per record id and quote, from the same tool the fake model reads."""
    data = listing(access)
    quotes = {source["id"]: source["quote"] for source in data["sources"]}
    return {item["record"]["id"]: {quotes[key]: key for key in item["sources"]}
            for item in data["records"]}


def list_answer(access, heading="Odalar şunlar:"):
    sources = ids(access)
    lines = [f"- Bahçe odası: {2} kişilik [{sources['rec-room']['2']}]",
             f"- **Deniz Odası** – 3 kişilik [{sources['rec-sea']['3']}]",
             f"- Family suite (4 kişi) [{sources['rec-family']['4']}] [{sources['rec-family']['Family suite']}]"]
    return "\n".join(([heading] if heading else []) + lines), sources


def test_list_collection_returns_every_approved_record_with_its_own_sources(access):
    data = listing(access)
    assert data["mode"] == "approved" and data["revision_id"] == "r1"
    records = {item["record"]["id"]: item for item in data["records"]}
    assert set(records) == {"rec-room", "rec-sea", "rec-family"}  # No proposed/rejected rows.
    garden = records["rec-room"]["record"]
    assert garden == {"id": "rec-room", "name": "Garden room", "capacity": 2,
                      "i18n": {"tr": {"name": "Bahçe odası"}}}  # size_m2 not requested.
    by_id = {source["id"]: source for source in data["sources"]}
    assert {by_id[key]["quote"] for key in records["rec-room"]["sources"]} == {
        "Garden room", "Bahçe odası", "2"}
    assert "32" not in {source["quote"] for source in data["sources"]}
    assert all(set(item["sources"]) <= by_id.keys() for item in data["records"])
    for source in data["sources"]:
        assert (source["document_name"], source["locator"]) == ("odalar.txt", "§1 p.1")
    # Same id derivation as the other tools: list citations resolve to get_record sources.
    record = access.call("get_record", {"collection": "rooms", "id": "rec-room"})
    assert set(records["rec-room"]["sources"]) <= {source["id"] for source in record["sources"]}
    everything = access.call("list_collection", {"collection": "rooms"})
    assert next(item for item in everything["records"]
                if item["record"]["id"] == "rec-room")["record"]["size_m2"] == 32
    preview = listing(access, mode="preview")
    assert {item["record"]["id"] for item in preview["records"]} >= {"rec-proposed"}
    assert all("review_state" in item for item in preview["records"])
    for arguments in ({"collection": "rooms", "fields": ["price"]},
                      {"collection": "rooms", "fields": "capacity"},
                      {"collection": "rooms", "extra": True}):
        with pytest.raises(ToolInvalid):
            access.call("list_collection", arguments)


@pytest.mark.parametrize("heading", ["Odalar şunlar:", "Şu odalar var:", "## Odalar:",
                                     "Bilgiler şöyle:", None])
def test_list_answer_with_one_citation_per_item_is_accepted(access, heading):
    answer, sources = list_answer(access, heading)
    model = FakeModel([LIST_CALL, {"content": answer}])
    result = ask_result(QUESTION, access, model)
    assert not result.abstained and result.answer == answer
    cited = {key for record in sources.values() for quote, key in record.items()
             if quote in {"2", "3", "4", "Family suite"}}
    assert {source["id"] for source in result.sources} == cited
    assert len(model.calls) == 2  # One collection read, one answer, no repair.
    assert "list_collection" in model.calls[0][0][0]["content"]  # Instructed in the system prompt.


def test_detail_lines_and_cited_summary_lines_are_accepted(access):
    sources = ids(access)
    answer = (f"Odalar:\n- Garden room [{sources['rec-room']['Garden room']}]\n"
              f"  - 2 kişilik [{sources['rec-room']['2']}]\n"
              f"- Sea room [{sources['rec-sea']['Sea room']}]\n"
              f"En geniş oda 4 kişilik Family suite [{sources['rec-family']['4']}].")
    result = ask_result(QUESTION, access, FakeModel([LIST_CALL, {"content": answer}]))
    assert not result.abstained


@pytest.mark.parametrize("mutate", [
    # An item that is not in the approved collection, even with a real read source.
    lambda answer, s: answer + f"\n- Kral Dairesi: 6 kişilik [{s['rec-room']['2']}]",
    # Proposed (unapproved) record named from outside the approved publication.
    lambda answer, s: answer + f"\n- Hidden room [{s['rec-room']['2']}]",
    # A real item cited with another record's source.
    lambda answer, s: answer.replace(s["rec-sea"]["3"], s["rec-room"]["2"]),
    # Name prefix followed by an invented item.
    lambda answer, s: answer.replace("- **Deniz Odası** –", "- Deniz Odası ve Kral Dairesi:"),
    # Uncited item line.
    lambda answer, s: answer + "\n- Sea room: 3 kişilik",
    # Unread / invented source.
    lambda answer, s: answer + "\n- Sea room [src_invented]",
    # Detail line citing another record.
    lambda answer, s: answer + f"\n  - 2 kişilik [{s['rec-room']['2']}]",
    # Headings that state facts are not headings.
    lambda answer, s: answer.replace("Odalar şunlar:", "Otelde 3 oda var:"),
    lambda answer, s: answer.replace("Odalar şunlar:", "Odalar şunlar, havuz yok:"),
    lambda answer, s: answer.replace("Odalar şunlar:", "Deniz manzaralı odalar:"),
    lambda answer, s: answer.replace("Odalar şunlar:", "Odalar şunlar"),
    lambda answer, s: answer + "\nTümü ücretsizdir.",
    lambda answer, s: answer + "\nSonraki liste:",
    lambda answer, s: "Bilmiyorum.",
])
def test_invented_unsupported_or_uncited_list_lines_abstain(access, mutate):
    answer, sources = list_answer(access)
    model = FakeModel([LIST_CALL, {"content": mutate(answer, sources)}])
    result = ask_result(QUESTION, access, model)
    assert result.abstained and result.sources == [] and result.answer == "Bilmiyorum."
    assert len(model.calls) == 2  # Rejected list answers are never sent to repair.


def test_unknown_question_after_list_read_abstains(access):
    model = FakeModel([LIST_CALL, {"content": "Bilmiyorum."}])
    assert ask_result("Helikopter pisti var mı?", access, model).abstained


def test_single_fact_answers_keep_the_existing_sentence_rule(access):
    record = access.call("get_record", {"collection": "rooms", "id": "rec-room"})
    sources = {source["quote"]: source["id"] for source in record["sources"]}
    labels = f"- Kapasite: 2 kişi [{sources['2']}]\n- Büyüklük: 32 m² [{sources['32']}]"
    assert not ask_result("Bahçe odası?", access, FakeModel([invocation(), {"content": labels}])).abstained
    uncited = f"Bahçe odası:\n- Kapasite: 2 kişi [{sources['2']}]\n- 32 m² büyüklüğündedir."
    assert ask_result("Bahçe odası?", access, FakeModel([invocation(), {"content": uncited}])).abstained


def test_search_results_also_identify_listed_records(access):
    search = access.call("search_records", {"collection": "rooms", "query": "room"})
    by_record = {entry["record"]["id"]: {s["quote"]: s["id"] for s in entry["sources"]}
                 for entry in search["records"]}
    answer = (f"Odalar:\n- Garden room [{by_record['rec-room']['Garden room']}]\n"
              f"- Sea room [{by_record['rec-sea']['Sea room']}]")
    calls = invocation("search_records", {"collection": "rooms", "query": "room"})
    assert not ask_result("Hangi odalar var?", access, FakeModel([calls, {"content": answer}])).abstained


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_question_deadline_stops_the_loop(access, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(ask_module, "time", clock)

    class SlowModel(FakeModel):
        def complete(self, messages, tools):
            clock.now += 70
            return super().complete(messages, tools)

    model = SlowModel([LIST_CALL, LIST_CALL, LIST_CALL])
    with pytest.raises(ModelTimeout):
        ask_result(QUESTION, access, model, deadline=clock.now + 120)
    assert len(model.calls) == 2


def test_client_bounds_each_request_and_retry_by_the_question_deadline(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(ask_module, "time", clock)
    timeouts = []

    def handler(request):
        timeouts.append(request.extensions["timeout"]["read"])
        if len(timeouts) == 1:
            clock.now += 119.5
            return httpx.Response(503)
        clock.now += 1
        raise httpx.ReadTimeout("slow", request=request)

    model = OpenAICompatibleClient("https://model.example/v1", "fixture-model", "", timeout=60,
                                   total_timeout=120, transport=httpx.MockTransport(handler))
    try:
        assert model.client.timeout.read == 60
        with pytest.raises(ModelUnavailable):
            model.complete([], [])  # 503, then no retry: the back-off would pass the deadline.
        assert timeouts == [60]
        with pytest.raises(ModelTimeout):
            model.complete([], [])  # Remaining 0.5 s bounds the request; no retry after it.
        assert timeouts == [60, 0.5]
        with pytest.raises(ModelTimeout):
            model.complete([], [])  # Deadline passed: no request is sent.
        assert timeouts == [60, 0.5]
    finally:
        model.close()


def test_dene_uses_configured_timeouts_and_returns_504_after_question_limit(setup, monkeypatch):
    client, store, _, _ = setup
    store.publish(rooms_revision("r2"))
    clock = Clock()
    monkeypatch.setattr(ask_module, "time", clock)
    monkeypatch.setattr(try_ai, "time", clock)
    built = []

    class SlowModel(test_u1_try.ReadingModel):
        def complete(self, messages, tools):
            clock.now += 70
            self.messages.append(messages)
            return LIST_CALL

    def factory(*args, **kwargs):
        built.append(kwargs)
        model = SlowModel()
        built.append(model)
        return model

    monkeypatch.setattr(try_ai, "OpenAICompatibleClient", factory)
    response = client.post(PATH, json={"question": QUESTION})
    assert response.status_code == 504
    assert response.json()["detail"] == try_ai.TIMEOUT
    assert built[0] == {"timeout": 60, "total_timeout": 120}
    assert len(built[1].messages) == 2 and built[1].closed
    monkeypatch.setattr(get_settings(), "dene_question_timeout_seconds", 300)
    monkeypatch.setattr(get_settings(), "dene_model_timeout_seconds", 90)
    assert client.post(PATH, json={"question": QUESTION}).status_code == 504
    assert built[2] == {"timeout": 90, "total_timeout": 300}
    assert len(built[3].messages) == 5


def test_dene_api_answers_a_cited_list_with_unchanged_contract(setup, monkeypatch):
    client, store, _, _ = setup
    store.publish(rooms_revision("r2"))
    answer, _ = list_answer(AIAccess(store, "workspace-example"))
    model = test_u1_try.ReadingModel(calls=LIST_CALL, answer=lambda data: answer)
    monkeypatch.setattr(try_ai, "OpenAICompatibleClient", lambda *a, **kw: model)
    response = client.post(PATH, json={"question": QUESTION})
    result = response.json()
    assert response.status_code == 200 and not result["abstained"] and result["answer"] == answer
    assert set(result) == {"answer", "abstained", "workspace_id", "revision_id", "mode", "sources"}
    assert result["revision_id"] == "r2" and len(result["sources"]) == 4
    assert all(source["id"] in answer for source in result["sources"])


# Each key item is one name or a list of accepted names (e.g. English and Turkish).
ITEMS = [["Garden room", "Bahçe odası"], ["Sea room", "Deniz Odası"], "Family suite"]
LIST_QUESTIONS = [{"id": "rooms", "kind": "list", "question": QUESTION, "items": ITEMS},
                  {"id": "helipad", "kind": "unknown", "question": "Helikopter pisti var mı?"}]


class ClosingModel(FakeModel):
    closed = False

    def close(self):
        self.closed = True


def test_measurement_scores_list_questions_items_and_latency(access):
    answer, _ = list_answer(access)
    models = []

    def factory():
        responses = ([LIST_CALL, {"content": answer}] if len(models) % 2 == 0
                     else [invocation(), {"content": "Bilmiyorum."}])
        models.append(ClosingModel(responses))
        return models[-1]

    report = benchmark.measure(LIST_QUESTIONS, access, factory, repetitions=3, question_timeout=120)
    assert report["passed"] and report["correct_with_sources"] == report["known_runs"] == 3
    assert report["invented_items"] == report["missing_items"] == report["answered_on_unknown"] == 0
    assert report["invented_sources"] == report["timeouts"] == 0
    assert set(report["latency_seconds"]) == {"mean", "p50", "max"}
    assert all(isinstance(row["seconds"], float) for row in report["results"])
    assert "Garden room" not in json.dumps(report) and all(model.closed for model in models)


def test_measurement_counts_invented_and_missing_items_and_timeouts(access, monkeypatch):
    answer, sources = list_answer(access)
    answers = iter([answer + f"\n- Kral Dairesi [{sources['rec-room']['2']}]",
                    "\n".join(answer.splitlines()[:-1])])

    def fake(question, trace, model, **kwargs):
        if question != QUESTION:
            return AskResult()
        data = trace.call("list_collection", {"collection": "rooms", "fields": ["capacity"],
                                              "mode": "approved"})
        text = next(answers)
        cited = set(ask_module.CITATION.findall(text))
        return AskResult(text, False, [s for s in data["sources"] if s["id"] in cited])

    monkeypatch.setattr(benchmark, "ask_result", fake)
    report = benchmark.measure(LIST_QUESTIONS, access, lambda: ClosingModel([]), repetitions=2)
    assert report["invented_items"] == 1 and report["missing_items"] == 1
    assert report["incorrect_on_known"] == 2 and not report["passed"]

    class SlowModel(ClosingModel):
        def complete(self, messages, tools):
            raise ModelTimeout("private detail")

    monkeypatch.undo()
    report = benchmark.measure(LIST_QUESTIONS, access, lambda: SlowModel([]), repetitions=1)
    assert report["timeouts"] == 2 and report["errors"] == 2 and not report["passed"]
    assert {row["outcome"] for row in report["results"]} == {"timeout"}


@pytest.mark.parametrize("mutation", [
    lambda qs: [{**qs[0], "items": []}, qs[1]],
    lambda qs: [{**qs[0], "items": "Garden room"}, qs[1]],
    lambda qs: [{**qs[0], "items": [["Garden room", ""]]}, qs[1]],
    lambda qs: [{**qs[0], "claims": [{"pattern": "2"}]}, qs[1]],
    lambda qs: qs[:1],
])
def test_list_key_requires_items_and_an_unknown_question(mutation):
    assert benchmark.validate_questions(json.loads(json.dumps(LIST_QUESTIONS)))
    with pytest.raises(ValueError):
        benchmark.validate_questions(mutation(json.loads(json.dumps(LIST_QUESTIONS))))
