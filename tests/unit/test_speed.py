"""WP113: fake transports, independent fixture fields, grounded server-rendered lists."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
import test_dene_lists as dene_tests
import test_u1_pipeline as pipeline_tests
import test_u1_settings as settings_tests
import test_u1_try as try_tests
from docgrain_access.ask import (
    CITATION,
    ModelUnavailable,
    OpenAICompatibleClient,
    ask_result,
)
from docgrain_api import try_ai, workspace_settings
from docgrain_api.records_repository import RecordsRepository
from docgrain_records.discovery import DiscoveryClient
from docgrain_records.extractor import extract
from docgrain_records.match import PairClient
from docgrain_records.model import ChatClient
from docgrain_records.models import ExtractionUsage
from docgrain_worker import records_pipeline
from test_ai_clients import FakeModel, invocation
from test_dene_lists import LIST_CALL, QUESTION, listing, room, rooms_revision
from test_sectioned_extraction import (
    candidate,
    context_for,
    fact,
    request_parts,
    response,
)
from test_u1_pipeline import start
from test_u1_settings import create, update

access = dene_tests.access
pipeline_setup = pipeline_tests.setup
settings_store = settings_tests.settings_store
try_setup = try_tests.setup

spec = importlib.util.spec_from_file_location("speed_benchmark", Path("benchmarks/speed.py"))
speed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speed)


@pytest.mark.parametrize("client_type", [ChatClient, DiscoveryClient, PairClient, OpenAICompatibleClient])
@pytest.mark.parametrize("options", [{}, {"reasoning_effort": "low", "max_tokens": 8192}])
def test_every_client_options_and_per_physical_request_measurement(client_type, options, monkeypatch):
    requests, pauses, observed = [], [], []
    monkeypatch.setattr("time.sleep", pauses.append)

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert {key: payload[key] for key in ("reasoning_effort", "max_tokens") if key in payload} == options
        if len(requests) == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30,
                      "completion_tokens_details": {"reasoning_tokens": 4}}})

    chat = client_type("https://model.example/v1", "synthetic", "synthetic-key",
                       transport=httpx.MockTransport(handler), on_usage=observed.append, **options)
    try:
        if client_type is OpenAICompatibleClient:
            chat.complete([], [])
        else:
            chat.complete([])
    finally:
        chat.close()
    assert pauses == [1] and len(observed) == 2
    assert [call["attempt"] for call in observed] == [1, 2]
    assert [call["status_code"] for call in observed] == [429, 200]
    assert all(call["wall_seconds"] >= 0 for call in observed)
    assert observed[1]["reasoning_tokens"] == 4
    assert observed[1]["prompt_tokens"] == 20 and observed[1]["completion_tokens"] == 10
    assert "prompt_tokens" not in observed[0]
    assert "synthetic-key" not in json.dumps(observed)


@pytest.mark.parametrize("client_type", [ChatClient, OpenAICompatibleClient])
def test_failed_transport_measured_without_invented_usage(client_type):
    def handler(request):
        raise httpx.ConnectError("private", request=request)
    chat = client_type("https://model.example/v1", "synthetic", "key",
                       transport=httpx.MockTransport(handler))
    try:
        with pytest.raises((httpx.ConnectError, ModelUnavailable)):
            if client_type is OpenAICompatibleClient:
                chat.complete([], [], attempts=1)
            else:
                chat.retries = 0
                chat.complete([])
        assert len(chat.calls) == 1 and chat.calls[0]["status_code"] is None
        assert "prompt_tokens" not in chat.calls[0] and "private" not in json.dumps(chat.calls)
    finally:
        chat.close()


@pytest.mark.parametrize("client_type", [ChatClient, OpenAICompatibleClient])
def test_physical_wall_time_excludes_retry_backoff(client_type, monkeypatch):
    from types import SimpleNamespace

    import docgrain_access.ask as ask_module
    import docgrain_records.model as model_module
    now = [0.0]
    def sleep(delay):
        now[0] += delay
    clock = SimpleNamespace(monotonic=lambda: now[0], sleep=sleep)
    monkeypatch.setattr(model_module if client_type is ChatClient else ask_module, "time", clock)
    requests = []
    def handler(request):
        requests.append(request)
        now[0] += .25 if len(requests) == 1 else .5
        return httpx.Response(429 if len(requests) == 1 else 200,
                              json={"choices": [{"message": {"content": "{}"}}]})
    chat = client_type("https://model.example/v1", "fake", "key", transport=httpx.MockTransport(handler))
    try:
        chat.complete([], []) if client_type is OpenAICompatibleClient else chat.complete([])
        assert [call["wall_seconds"] for call in chat.calls] == [.25, .5]
        assert now[0] == 1.75  # The whole stage includes the one-second backoff.
    finally:
        chat.close()


def test_settings_roundtrip_isolation_validation_and_resolved_options(settings_store):
    client, _, _, _ = settings_store
    a, b = create(client), create(client)
    url = f"/v1/workspaces/{a}/model"
    result = client.put(url, json=update(reasoning_effort="low", max_tokens=8192))
    assert result.status_code == 200
    resolved = workspace_settings.resolve_workspace_model(a)
    assert resolved.reasoning_effort == "low" and resolved.max_tokens == 8192
    assert client.get(url).json()["reasoning_effort"] == "low"
    assert client.get(f"/v1/workspaces/{b}/model").json()["reasoning_effort"] is None
    for bad in ({"reasoning_effort": "guess"}, {"max_tokens": 0}, {"max_tokens": True},
                {"max_tokens": 1.5}, {"api_key": "secret"}):
        assert client.put(url, json=update(**bad)).status_code == 422
    assert client.put(url, json=update(reasoning_effort="none", model="gemini-3-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai")).status_code == 422
    assert client.put(url, json=update()).json()["reasoning_effort"] is None


def test_pipeline_records_all_stages_calls_tokens_and_passes_workspace_options(pipeline_setup, monkeypatch):
    from types import SimpleNamespace
    setup = pipeline_setup
    now = [0.0]
    monkeypatch.setattr(records_pipeline, "time", SimpleNamespace(monotonic=lambda: now[0]))
    setup.settings.update(reasoning_effort="medium", max_tokens=4096)
    key = start(setup)

    def handler(request):
        payload = json.loads(request.content)
        assert payload["reasoning_effort"] == "medium" and payload["max_tokens"] == 4096
        body = setup.model.handle(request).json()
        now[0] += 2
        body["usage"] = {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30,
                         "completion_tokens_details": {"reasoning_tokens": 4}}
        return httpx.Response(200, json=body)

    records_pipeline.process_job(key, httpx.MockTransport(handler), lambda *_: deepcopy(setup.docs))
    job = setup.memory.locate(key)
    assert job["status"] == "done"
    telemetry = job["metadata"]["speed"]
    assert set(telemetry["stages"]) == {"structure", "discover", "accept_schema", "extract", "match",
                                        "merge", "publish"}
    assert len(telemetry["calls"]) == 5
    assert telemetry["stages"]["discover"]["prompt_tokens"] == 20
    assert telemetry["stages"]["discover"]["wall_seconds"] == 2
    assert telemetry["stages"]["extract"]["wall_seconds"] == 8
    assert telemetry["stages"]["extract"]["completion_tokens"] == 40
    assert telemetry["stages"]["extract"]["reasoning_tokens"] == 16
    assert all(stage["wall_seconds"] >= 0 for stage in telemetry["stages"].values())
    assert telemetry["options"]["reasoning_effort"] == "medium"
    public = setup.client.get(f"/v1/workspaces/{setup.docs[0].source.workspace_id}/record-jobs/{key}").json()
    assert public["speed"] == telemetry
    assert "Bilgileri çıkar" in speed.stage_table(public)


def test_grouped_extraction_reduces_requests_with_identical_verified_fields_and_order():
    source = context_for(["Garden room; Capacity: 2 people; Size: 32 m²; Pets are not allowed; Indoor pool."])
    records = [candidate("room_type", name=[fact("Garden room", "§1")],
                         capacity=[fact(2, "§1", "Capacity: 2 people")],
                         size_m2=[fact(32, "§1", "Size: 32 m²")]),
               candidate("policy", name=[fact("Pets", "§1")], text=[fact("Pets are not allowed", "§1")]),
               candidate("facility", name=[fact("Indoor pool", "§1")])]
    outputs, usages = [], []
    for grouped in (False, True):
        usage = ExtractionUsage()
        def handler(request):
            context, focus, _ = request_parts(request)
            assert "Capacity: 2 people" in context
            return response([record for record in records if focus is None or record["type"] == focus])
        chat = ChatClient("https://model.example/v1", "fake", "key", transport=httpx.MockTransport(handler))
        try:
            result = extract(source, "doc_example", "en", chat, grouped_passes=grouped, concurrency=6, usage=usage)
        finally:
            chat.close()
        assert not result.rejected and not result.failures
        outputs.append(result.model_dump(mode="json"))
        usages.append(usage)
    assert outputs[0] == outputs[1] and len(outputs[1]["records"]) == 3
    assert len(usages[0].calls) == 5 and len(usages[1].calls) == 1
    assert usages[1].prompt_tokens < usages[0].prompt_tokens


def render_call(ids=None, fields=None, **extra):
    return invocation("render_list", {"collection": "rooms", "record_ids": ids or [],
                                     "fields": fields or ["capacity"], **extra})


def test_server_list_rendering_returns_only_read_records_values_and_their_own_citations(access):
    model = FakeModel([LIST_CALL, render_call()])
    result = ask_result(QUESTION, access, model, render_lists=True)
    assert not result.abstained and len(result.answer.splitlines()) == 3
    data = listing(access)
    for line, item in zip(result.answer.splitlines(), data["records"], strict=True):
        record = item["record"]
        assert str(record["capacity"]) in line
        ids = set(CITATION.findall(line))
        assert ids and ids <= set(item["sources"])
        assert set(item["field_sources"]["capacity"]["primary"]) <= ids
    assert "Bahçe odası" in result.answer
    assert len(model.calls) == 2
    assert {source["id"] for source in result.sources} == set(CITATION.findall(result.answer))
    assert len(json.dumps(render_call(), ensure_ascii=False)) < len(result.answer)


@pytest.mark.parametrize("final", [
    render_call(ids=["invented"]), render_call(ids=["rec-proposed"]),
    render_call(fields=["price"]), render_call(fields=["capacity", "capacity"]),
    render_call(mode="preview"), render_call(workspace="foreign"),
    render_call(fields=["id"]), {"content": "Bilmiyorum."},
])
def test_unknown_or_invalid_server_list_selections_abstain(access, final):
    result = ask_result(QUESTION, access, FakeModel([LIST_CALL, final]), render_lists=True)
    assert result.abstained and result.sources == []
    assert ask_result(QUESTION, access, FakeModel([render_call()]), render_lists=True).abstained


def test_server_renderer_needs_field_evidence_not_another_fields_source(access):
    data = listing(access)
    data["records"][0]["field_sources"]["capacity"]["primary"] = []
    class MissingEvidence:
        def specs(self):
            return access.specs()
        def call(self, *args):
            return data
    assert ask_result(QUESTION, MissingEvidence(), FakeModel([LIST_CALL, render_call()]), render_lists=True).abstained


def test_twenty_five_records_render_in_two_model_turns(tmp_path):
    from docgrain_api.ai_access import AIAccess
    revision = rooms_revision()
    revision.records = [room(f"rec-{i}", f"Garden room {i}", f"Bahçe odası {i}", 2) for i in range(25)]
    store = RecordsRepository(tmp_path)
    store.publish(revision)
    access = AIAccess(store, "workspace-example")
    model = FakeModel([LIST_CALL, render_call()])
    result = ask_result(QUESTION, access, model, render_lists=True)
    assert not result.abstained and len(result.answer.splitlines()) == 25
    assert all(f"- Bahçe odası {i}:" in result.answer for i in range(25))
    assert len(model.calls) == 2


def test_server_list_honors_discovered_identity_field_instead_of_assuming_name(access):
    data = listing(access)
    for item in data["records"]:
        record = item["record"]
        record["title"] = record.pop("name")
        item["identity"] = "title"
        item["field_sources"]["title"] = item["field_sources"].pop("name")
        for translated in record.get("i18n", {}).values():
            translated["title"] = translated.pop("name")
    class Titles:
        def specs(self):
            return access.specs()
        def call(self, *args):
            return data
    result = ask_result(QUESTION, Titles(), FakeModel([LIST_CALL, render_call()]), render_lists=True)
    assert not result.abstained and "Bahçe odası" in result.answer


def test_server_list_sanitizes_source_citation_text_and_embedded_lines(access):
    data = listing(access)
    data["records"][0]["record"]["i18n"]["tr"]["name"] = "Garden room\n- Invented [src_injected]"
    class SourceText:
        def specs(self):
            return access.specs()
        def call(self, *args):
            return data
    result = ask_result(QUESTION, SourceText(), FakeModel([LIST_CALL, render_call()]), render_lists=True)
    assert not result.abstained and len(result.answer.splitlines()) == 3
    assert "src_injected" not in CITATION.findall(result.answer)


def test_speed_is_off_without_explicit_opt_in_and_tables_are_numeric(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("no network client without opt-in")
    monkeypatch.setattr(speed, "AccessClient", forbidden)
    monkeypatch.setattr(speed, "ChatClient", forbidden)
    assert speed.main([]) == 0 and "Model kapalı" in capsys.readouterr().out
    assert speed.usage_summary([{"attempt": 1}])["reasoning_tokens"] is None
    assert speed.latency([1, 2, 3, 4, 5])["p95"] == 5


def test_fixture_scorer_is_independent_of_model_output_and_gate_rejects_regressions():
    from types import SimpleNamespace
    empty = SimpleNamespace(records=[], rejected=[], failures=[])
    assert speed.score_extraction(empty)["field_accuracy"] == 0
    baseline = {"dene": {"correct_with_sources": 3}, "extraction": {"field_accuracy": 100}}
    candidate = {"dene": {"passed": True, "correct_with_sources": 3},
                 "extraction": {"field_accuracy": 98, "results": []}}
    assert not speed.gates(baseline, candidate)["extraction"]
    candidate["extraction"]["field_accuracy"] = 99
    assert speed.gates(baseline, candidate)["extraction"]
    assert speed.gates(baseline, candidate)["real_independent_key"] == "not_verified"


def test_dene_api_passes_workspace_options_and_server_rendering(try_setup, monkeypatch):
    from docgrain_api.settings import get_settings
    client, store, config, _ = try_setup
    config.update(reasoning_effort="low", max_tokens=2048)
    monkeypatch.setattr(get_settings(), "dene_server_lists", True)
    store.publish(rooms_revision("r2"))
    seen = []
    class Model(FakeModel):
        def close(self):
            pass
    def factory(*args, **kwargs):
        seen.append(kwargs)
        return Model([LIST_CALL, render_call()])
    monkeypatch.setattr(try_ai, "OpenAICompatibleClient", factory)
    result = client.post(try_tests.PATH, json={"question": QUESTION})
    assert result.status_code == 200 and not result.json()["abstained"]
    assert seen[0]["reasoning_effort"] == "low" and seen[0]["max_tokens"] == 2048
    assert len(result.json()["answer"].splitlines()) == 3


def test_benchmark_end_to_end_fake_transports_compare_accuracy_latency_and_tokens(access, tmp_path, monkeypatch, capsys):
    source = listing(access)["sources"]
    proof = next(item for item in source if item["quote"] == "2")
    questions = [{"id": "single", "kind": "known", "question": "Tek odanın kapasitesi?", "claims": [
        {"pattern": "2 kişilik", **{key: proof[key] for key in ("quote", "document_name", "locator")}}]},
        {"id": "list", "kind": "list", "question": QUESTION,
         "items": [["Garden room", "Bahçe odası"], ["Sea room", "Deniz Odası"], ["Family suite", "Aile Süiti"]]},
        {"id": "unknown", "kind": "unknown", "question": "Helikopter pisti?"}]
    key_path = tmp_path / "key.json"
    key_path.write_text(json.dumps(questions), encoding="utf-8")
    class LocalAccess:
        def specs(self):
            return access.specs()
        def call(self, *args):
            return access.call(*args)
        def close(self):
            pass
    monkeypatch.setattr(speed, "AccessClient", lambda *args: LocalAccess())

    def dene_handler(request):
        payload = json.loads(request.content)
        messages = payload["messages"]
        question = messages[1]["content"]
        read = next((json.loads(m["content"]) for m in messages if m["role"] == "tool"), None)
        if "Helikopter" in question:
            message = {"content": "Bilmiyorum."}
        elif read is None:
            message = LIST_CALL if question == QUESTION else invocation()
        elif question != QUESTION:
            message = {"content": f"Oda 2 kişilik [{proof['id']}]."}
        elif any(tool["function"]["name"] == "render_list" for tool in payload["tools"]):
            message = render_call()
        else:
            message = {"content": "\n".join(
                f"- {item['record']['name']}: Kişi sayısı {item['record']['capacity']} "
                + " ".join(f"[{key}]" for key in item["sources"]) for item in read["records"])}
        return httpx.Response(200, json={"choices": [{"message": message}], "usage": {
            "prompt_tokens": 20, "completion_tokens": len(json.dumps(message)) // 4,
            "completion_tokens_details": {"reasoning_tokens": 4}}})
    monkeypatch.setattr(speed, "OpenAICompatibleClient", lambda *args, **kwargs:
        OpenAICompatibleClient(*args, **kwargs, transport=httpx.MockTransport(dene_handler)))

    fixture = [candidate("room_type", name=[fact("Garden room", "§1")],
                         capacity=[fact(2, "§1", "Capacity: 2 people")], size_m2=[fact(32, "§1", "Size: 32 m²")]),
               candidate("facility", name=[fact("Indoor pool", "§2")],
                         hours=[fact("08:00–20:00", "§2", "Opening hours: 08:00–20:00")])
               | {"kind": [fact("pool", "§2", "Kind: pool")]},
               candidate("policy", name=[fact("Pets", "§3")], text=[fact("Pets are not allowed.", "§3")])]
    for record in fixture:
        for values in record.values():
            if isinstance(values, list):
                for value in values:
                    value["evidence"][0]["document_id"] = "doc_speed_fixture"
    def extraction_handler(request):
        _, focus, _ = request_parts(request)
        return response([record for record in fixture if focus is None or focus == record["type"]])
    monkeypatch.setattr(speed, "ChatClient", lambda *args, **kwargs:
        ChatClient(*args, **kwargs, transport=httpx.MockTransport(extraction_handler)))
    assert speed.main(["--enable-model", "--api-url", "https://api.example", "--workspace", "workspace-example",
                       "--base-url", "https://model.example/v1", "--model", "fake", "--questions", str(key_path),
                       "--repetitions", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [row["option"] for row in report["options"]] == ["baseline", "default", "none", "low", "medium"]
    assert all(row["extraction"]["field_accuracy"] == 100 for row in report["options"])
    assert report["options"][0]["extraction"]["usage"]["requests"] == 5
    assert report["options"][1]["extraction"]["usage"]["requests"] == 1
    assert report["options"][1]["dene"]["usage"]["completion_tokens"] < report["options"][0]["dene"]["usage"]["completion_tokens"]
    assert report["options"][1]["dene"]["passed"]
    assert not report["default_changed"] and "Garden room" not in json.dumps(report)
