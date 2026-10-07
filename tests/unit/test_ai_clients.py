"""MCP wire semantics and the reference loop use only fake HTTP/model clients."""

import importlib.util
import json
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path

import httpx
import pytest
from docgrain_access.ask import SYSTEM, OpenAICompatibleClient, ask
from docgrain_access.client import AccessClient, AccessError
from docgrain_access.mcp import MCPServer, serve
from docgrain_api.ai_access import AIAccess
from docgrain_api.records_repository import RecordsRepository
from test_records_export import fixture_revision


@pytest.fixture
def access(tmp_path):
    store = RecordsRepository(tmp_path)
    revision = fixture_revision()
    revision.documents[0].document_name = "rooms.txt"
    store.publish(revision)
    return AIAccess(store, "workspace-example")


class FakeModel:
    def __init__(self, messages):
        self.responses = iter(messages)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((json.loads(json.dumps(messages)), tools))
        return next(self.responses)


def invocation(name="get_record", arguments=None, call_id="call-1"):
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": call_id, "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments or {
                "collection": "rooms", "id": "rec-room",
            }),
        },
    }]}


def test_reference_loop_calls_tools_then_returns_resolvable_citations(access):
    source_id = next(s["id"] for s in access.call("get_record", {
        "collection": "rooms", "id": "rec-room"})["sources"] if s["quote"] == "2")
    model = FakeModel([invocation(), {"content": f"Oda iki kişiliktir [{source_id}]."}])
    answer = ask("Kaç kişi kalabilir?", access, model)
    assert f"Oda iki kişiliktir [{source_id}]" in answer
    assert '"document_name": "rooms.txt"' in answer and '"quote": "2"' in answer
    second_messages, tools = model.calls[1]
    assert second_messages[-1]["role"] == "tool"
    result = json.loads(second_messages[-1]["content"])
    assert result["mode"] == "approved" and result["record"]["capacity"] == 2
    assert all(t["function"]["parameters"]["properties"]["mode"]["enum"] == ["approved"]
               for t in tools)
    assert "untrusted DATA" in SYSTEM


@pytest.mark.parametrize("answer", ["It is definitely 5.", "Five [src_invented].", "Bilmiyorum."])
def test_abstains_without_a_real_tool_citation(access, answer):
    assert ask("Unknown fact?", access, FakeModel([{"content": answer}])) == "Bilmiyorum."
    assert ask("Unknown fact?", access, FakeModel([invocation(), {"content": answer}])) == "Bilmiyorum."


def test_empty_search_unknown_tool_invalid_arguments_and_loop_limit(access):
    missing = invocation("search_records", {"collection": "rooms", "query": "submarine"})
    model = FakeModel([missing, {"content": "There is a submarine [src_fake]."}])
    assert ask("Submarine?", access, model) == "Bilmiyorum."
    assert json.loads(model.calls[1][0][-1]["content"])["sources"] == []
    class FailingAccess:
        def specs(self):
            return access.specs()
        def call(self, *args):
            raise AccessError("HTTP 422")
    model = FakeModel([invocation("unknown"), {"content": "Bilmiyorum."}])
    assert ask("Unknown?", FailingAccess(), model) == "Bilmiyorum."
    assert "error" in json.loads(model.calls[1][0][-1]["content"])
    malformed = invocation()
    malformed["tool_calls"][0]["function"]["arguments"] = "[]"
    model = FakeModel([malformed, {"content": "Bilmiyorum."}])
    assert ask("Unknown?", access, model) == "Bilmiyorum."
    assert "error" in json.loads(model.calls[1][0][-1]["content"])
    assert ask("Loop?", access, FakeModel([invocation()] * 2), max_turns=2) == "Bilmiyorum."


def test_preview_requires_explicit_caller_choice_and_is_disclosed(access):
    preview_call = invocation(arguments={"collection": "rooms", "id": "rec-room", "mode": "preview"})
    model = FakeModel([preview_call, {"content": "Sea [src_fake]."}])
    assert ask("View?", access, model) == "Bilmiyorum."
    assert "error" in json.loads(model.calls[1][0][-1]["content"])
    source_id = next(s["id"] for s in access.call("get_record", {
        "collection": "rooms", "id": "rec-room", "mode": "preview"})["sources"] if s["quote"] == "Sea")
    model = FakeModel([preview_call, {"content": f"Kaynaklar çelişiyor [{source_id}]."}])
    answer = ask("View?", access, model, preview=True)
    assert answer.startswith("Önizleme")
    assert json.loads(model.calls[1][0][-1]["content"])["record"]["_meta"]["conflicts"]


def test_openai_compatible_http_payload_and_multi_tool_messages(access):
    requests = []
    source_id = access.call("get_record", {"collection": "rooms", "id": "rec-room"})["sources"][0]["id"]
    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url == "https://model.example/v1/chat/completions"
        assert payload["model"] == "synthetic-model"
        assert request.headers["authorization"] == "Bearer synthetic-key"
        if len(requests) == 1:
            first = invocation()
            second = invocation("search_records", {"collection": "rooms", "query": "Garden"}, "call-2")
            first["tool_calls"].extend(second["tool_calls"])
            message = first
        else:
            assert [m["tool_call_id"] for m in payload["messages"] if m["role"] == "tool"] == ["call-1", "call-2"]
            message = {"content": f"Garden room [{source_id}]."}
        return httpx.Response(200, json={"choices": [{"message": message}]})
    model = OpenAICompatibleClient("https://model.example/v1", "synthetic-model", "synthetic-key",
                                   transport=httpx.MockTransport(handler))
    try:
        assert "Garden room" in ask("Room?", access, model)
    finally:
        model.close()
    assert len(requests) == 2


def test_api_client_pins_schema_revision_and_forwards_mode(access):
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=access.specs())
        assert request.url.params["revision_id"] == "r1"
        body = json.loads(request.content)
        return httpx.Response(200, json=access.call(body["name"], body["arguments"]))
    client = AccessClient("https://api.example", "workspace-example", transport=httpx.MockTransport(handler))
    try:
        assert not requests  # Construction/import never calls a network.
        result = client.call("get_context", {"collection": "rooms", "mode": "preview"})
        assert result["mode"] == "preview" and len(requests) == 2
        assert client.specs()["revision_id"] == "r1"
        assert requests[-1].url.params["revision_id"] == "r1"
    finally:
        client.close()


def test_api_errors_are_clean_and_do_not_echo_response_body():
    def handler(request):
        return httpx.Response(404, text="Untrusted private server body")
    client = AccessClient("https://api.example", "ws", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AccessError, match=r"HTTP 404") as error:
            client.specs()
        assert "private" not in str(error.value)
    finally:
        client.close()


def rpc(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


def initialize(server, version="2025-06-18"):
    response = server.handle(rpc("initialize", {"protocolVersion": version,
        "capabilities": {}, "clientInfo": {"name": "synthetic", "version": "1"}}))
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    return response


def test_mcp_lifecycle_same_four_tools_schema_and_structured_sources(access):
    server = MCPServer(access)
    assert server.handle(rpc("tools/list"))["error"]["code"] == -32000
    assert initialize(server)["result"]["capabilities"] == {"tools": {}}
    tools = server.handle(rpc("tools/list"))["result"]["tools"]
    assert len(tools) == 4
    assert tools[1]["inputSchema"] == access.specs()["tools"][1]["function"]["parameters"]
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    result = server.handle(rpc("tools/call", {"name": "get_record", "arguments": {
        "collection": "rooms", "id": "rec-room"}}))["result"]
    assert result["structuredContent"] == json.loads(result["content"][0]["text"])
    assert result["structuredContent"]["mode"] == "approved"
    assert result["structuredContent"]["sources"][0]["document_name"] == "rooms.txt"
    assert server.handle(rpc("ping"))["result"] == {}
    assert server.handle(rpc("unknown"))["error"]["code"] == -32601
    assert server.handle(rpc("tools/call", {"name": "get_record", "arguments": []}))["error"]["code"] == -32602


def test_mcp_older_version_negotiation_and_tool_error(access):
    class Unavailable:
        def call(self, *args):
            raise AccessError("Docgrain read failed (HTTP 404)")
    server = MCPServer(Unavailable())
    assert initialize(server, "2024-11-05")["result"]["protocolVersion"] == "2024-11-05"
    result = server.handle(rpc("tools/call", {"name": "unknown"}))["result"]
    assert result["isError"] is True and "structuredContent" not in result
    server = MCPServer(access)
    assert initialize(server, "future-version")["result"]["protocolVersion"] == "2025-06-18"


def test_mcp_stdio_newline_framing_parse_errors_and_notifications(access):
    messages = [rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "synthetic", "version": "1"}}),
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                rpc("tools/call", {"name": "get_context", "arguments": {"collection": "rooms"}}, id=2)]
    output = StringIO()
    serve(access, StringIO("bad json\n[]\n" + "\n".join(json.dumps(m) for m in messages) + "\n"), output)
    lines = output.getvalue().splitlines()
    assert len(lines) == 4
    results = [json.loads(line) for line in lines]
    assert results[0]["error"]["code"] == -32700
    assert results[1]["error"]["code"] == -32600
    assert results[-1]["id"] == 2
    assert "Bahçe odası" in results[-1]["result"]["content"][0]["text"]


def test_mcp_executable_subprocess_only_writes_json_rpc():
    # No tool invoked, so the synthetic API endpoint is never contacted.
    env = dict(os.environ, PYTHONPATH=str(Path("packages/access").resolve()))
    result = subprocess.run([sys.executable, "-m", "docgrain_access.mcp", "--api-url",
                             "https://api.example", "--workspace", "synthetic"],
                            input=json.dumps(rpc("ping")) + "\n", text=True, encoding="utf-8",
                            capture_output=True, env=env, timeout=20, check=False)
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout) == {"jsonrpc": "2.0", "id": 1, "result": {}}


def test_example_is_off_by_default_even_with_configuration(monkeypatch, capsys):
    path = Path("docs/examples/ask.py")
    spec = importlib.util.spec_from_file_location("ask_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def forbidden(*args, **kwargs):
        pytest.fail("No client may be created without --enable-model")
    monkeypatch.setattr(module, "AccessClient", forbidden)
    monkeypatch.setattr(module, "OpenAICompatibleClient", forbidden)
    monkeypatch.setenv("AI_API_KEY", "synthetic-key")
    assert module.main(["Room?"]) == 0
    assert "Model kapalı" in capsys.readouterr().out
