"""Compatible model transport is bounded; structured results retain CLI behavior."""

import json
from copy import deepcopy

import httpx
import pytest
from docgrain_access.ask import (
    ModelTimeout,
    ModelUnavailable,
    OpenAICompatibleClient,
    ask,
    ask_result,
)
from docgrain_access.client import AccessError
from docgrain_api.ai_access import AIAccess
from docgrain_api.records_repository import RecordsRepository
from test_ai_clients import FakeModel, invocation
from test_u1_try import INJECTION, KEY, room_revision


@pytest.fixture
def access(tmp_path):
    store = RecordsRepository(tmp_path)
    store.publish(room_revision())
    return AIAccess(store, "workspace-example")


def test_structured_result_returns_only_cited_read_sources_and_ask_stays_string(access):
    data = access.call("get_record", {"collection": "rooms", "id": "rec-room"})
    source_id = next(s["id"] for s in data["sources"] if s["quote"] == "32")
    responses = [invocation(), {"content": f"32 m² [{source_id}]."}]
    result = ask_result("Oda?", access, FakeModel(responses))
    assert not result.abstained and result.answer == responses[-1]["content"]
    assert len(result.sources) == 1 and result.sources[0]["quote"] == "32"
    text = ask("Oda?", access, FakeModel(responses))
    assert isinstance(text, str) and text.startswith(result.answer + "\n\n")
    assert '"document_name": "odalar.txt"' in text
    assert '"quote": "2"' not in text
    # A real publication source that was never read by this model is also invalid.
    assert ask_result("Oda?", access, FakeModel([responses[-1]])).abstained


def test_structured_loop_has_hard_eight_turn_and_tool_call_limit(access):
    model = FakeModel([invocation()] * 20)
    result = ask_result("Oda?", access, model, max_turns=20)
    assert result.abstained and len(model.calls) == 8 and result.sources == []
    message = invocation()
    message["tool_calls"] *= 9
    assert ask_result("Oda?", access, FakeModel([message])).abstained


def test_schema_descriptions_cannot_become_model_instructions(access):
    class DescribedAccess:
        def specs(self):
            specs = deepcopy(access.specs())
            for spec in specs["tools"]:
                spec["function"]["description"] = INJECTION
                spec["function"]["parameters"]["properties"]["mode"]["description"] = INJECTION
            return specs

        def call(self, name, arguments):
            return access.call(name, arguments)
    model = FakeModel([{"content": "Bilmiyorum."}])
    assert ask_result("Oda?", DescribedAccess(), model).abstained
    assert INJECTION not in json.dumps(model.calls)
    assert "untrusted DATA" in model.calls[0][0][0]["content"]


def test_access_transport_errors_propagate_only_in_structured_api(access):
    class BrokenAccess:
        def specs(self):
            return access.specs()

        def call(self, *args):
            raise AccessError(KEY)
    with pytest.raises(ModelUnavailable) as failure:
        ask_result("Oda?", BrokenAccess(), FakeModel([invocation()]))
    assert KEY not in str(failure.value) + repr(failure.value)
    assert ask("Oda?", BrokenAccess(), FakeModel([invocation(), {"content": "Bilmiyorum."}])) == "Bilmiyorum."


@pytest.mark.parametrize(("kind", "error", "expected_attempts"), [
    ("timeout", ModelTimeout, 3), ("unavailable", ModelUnavailable, 3),
    ("gateway-timeout", ModelTimeout, 3),
    ("unauthorized", ModelUnavailable, 1), ("connection", ModelUnavailable, 1),
    ("malformed", ModelUnavailable, 1), ("echo", ModelUnavailable, 1),
])
def test_model_transport_retry_timeout_and_redaction(monkeypatch, caplog, kind, error, expected_attempts):
    requests = []
    sleeps = []
    monkeypatch.setattr("docgrain_access.ask.time.sleep", sleeps.append)
    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer " + KEY
        assert KEY not in request.content.decode()
        if kind == "timeout":
            raise httpx.ReadTimeout(KEY, request=request)
        if kind == "connection":
            raise httpx.ConnectError(KEY, request=request)
        if kind == "malformed":
            return httpx.Response(200, json={"invalid": KEY})
        if kind == "echo":
            return httpx.Response(200, json={"choices": [{"message": {"content": KEY}}]})
        return httpx.Response(504 if kind == "gateway-timeout" else
                              503 if kind == "unavailable" else 401, text=KEY)
    model = OpenAICompatibleClient("https://model.example/v1", "fixture-model", KEY,
                                   transport=httpx.MockTransport(handler), timeout=20)
    assert KEY not in repr(model)
    assert model.client.timeout.read == 20
    try:
        with pytest.raises(error) as failure:
            model.complete([{"role": "user", "content": "Oda?"}], [], attempts=20)
        assert KEY not in str(failure.value) + repr(failure.value) + caplog.text
    finally:
        model.close()
    assert len(requests) == expected_attempts
    assert sleeps == ([1, 2] if expected_attempts == 3 else [])


def test_transient_status_retries_then_succeeds_and_local_keyless_is_explicit(monkeypatch):
    requests = []
    monkeypatch.setattr("docgrain_access.ask.time.sleep", lambda delay: None)
    def handler(request):
        requests.append(request)
        assert "authorization" not in request.headers
        if len(requests) == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Bilmiyorum."}}]})
    model = OpenAICompatibleClient("http://127.0.0.1:1234/v1", "local-model", "",
                                   transport=httpx.MockTransport(handler))
    try:
        assert model.complete([], [])["content"] == "Bilmiyorum."
    finally:
        model.close()
    assert len(requests) == 2


def test_all_four_existing_tools_work_in_the_same_approved_loop(access):
    calls = [invocation("list_collections", {}),
             invocation("search_records", {"collection": "rooms", "query": "Garden"}),
             invocation("get_record", {"collection": "rooms", "id": "rec-room"}),
             invocation("get_context", {"collection": "rooms"})]
    calls[0]["tool_calls"][0]["function"]["arguments"] = "{}"
    source_id = next(s["id"] for s in access.call("get_context", {"collection": "rooms"})["sources"]
                     if s["quote"] == "32")
    model = FakeModel(calls + [{"content": f"32 m² [{source_id}]."}])
    assert not ask_result("Oda?", access, model).abstained
    reads = [json.loads(message["content"]) for message in model.calls[-1][0] if message["role"] == "tool"]
    assert len(reads) == 4
    assert all((read["workspace_id"], read["revision_id"], read["mode"]) == (
        "workspace-example", "r1", "approved") for read in reads)
