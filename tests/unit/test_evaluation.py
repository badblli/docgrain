import json

import httpx
from docgrain_eval.api import PublishedAPI, build_context
from docgrain_eval.cli import main
from docgrain_eval.golden import Question, TableFact
from docgrain_eval.model import ChatClient
from docgrain_eval.scoring import citation, correct, normalize, number, parse_json
from docgrain_eval.tables import check_fact


def question(answer_type="text", expected="İskele", **overrides):
    data = {"id": "q1", "workspace_id": "ws_local", "document_ids": ["d1"],
            "question": "Nerede?", "answer_type": answer_type, "expected": expected,
            "accept": [], "evidence": [{"document_id": "d1", "page": 2, "quote": "İskele"}],
            "category": "place", "difficulty": "lookup"}
    data.update(overrides)
    return Question.model_validate(data)


def test_scoring_and_json_paths():
    assert parse_json('```json\n{"answer":"evet"}\n```')["answer"] == "evet"
    assert normalize("İSKELE  IĞDIR") == "iskele igdir"
    assert number("1.234,50 m²") == 1234.5
    assert correct(question(), {"answer": "Burada iskele vardır", "abstained": False})
    assert correct(question("number", {"value": "1.234,5", "unit": "m²"}),
                   {"value": "1234,5 metrekare", "abstained": False})
    assert not correct(question("number", {"value": 12, "unit": "m²"}),
                       {"value": "12 m", "abstained": False})
    assert correct(question("list", ["İskele", "Plaj"]),
                   {"answer": "iskele ve plaj", "abstained": False})
    assert correct(question("time_range", "09:00-18:00"),
                   {"answer": "9:00–18:00", "abstained": False})
    assert correct(question("unanswerable", None), {"abstained": True})
    assert not correct(question(), {"answer": "İskele", "abstained": True})
    assert citation(question(), {"citations": [{"document_id": "d1", "locator": "page 2"}]}) == (True, True)


def test_mixed_turkish_english_casefold():
    assert normalize("WI-FI") == normalize("Wi-Fi")
    assert normalize("SEA GYM") == normalize("Sea Gym")
    assert normalize("ışık") == normalize("isik")


def test_retry_fallback_and_no_key_in_output(capsys):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429)
        if len(calls) == 2:
            return httpx.Response(400)
        return httpx.Response(200, json={"choices": [{"message": {"content":
                              '```json\n{"answer":"evet","abstained":false}\n```'}}],
                                         "usage": {"total_tokens": 4}})

    chat = ChatClient("https://example.test/v1", "test", "top-secret", transport=httpx.MockTransport(handler))
    try:
        raw, parsed, usage = chat.complete([{"role": "user", "content": "Hi"}])
    finally:
        chat.close()
    assert parsed["answer"] == "evet" and usage["total_tokens"] == 4
    assert len(calls) == 3
    assert "response_format" not in json.loads(calls[-1].content)
    assert "top-secret" not in raw + capsys.readouterr().out


def test_context_and_dry_run_no_model(tmp_path, capsys, monkeypatch):
    def handler(request):
        path = request.url.path
        if path == "/v1/documents":
            return httpx.Response(200, json=[{"document": {"id": "d1", "filename": "a.txt",
                                                    "workspace_id": "ws_local"}}])
        if path.endswith("/knowledge"):
            return httpx.Response(200, json={"latest_revision_id": "r1"})
        return httpx.Response(200, text="<!-- object:n1; evidence:e1 -->\nMerhaba")

    api = PublishedAPI("https://example.test", httpx.Client(
        base_url="https://example.test", transport=httpx.MockTransport(handler)))
    context, revisions = build_context(api, "ws_local")
    assert "[d1] a.txt" in context and revisions == {"d1": "r1"}
    path = tmp_path / "questions.jsonl"
    path.write_text(question().model_dump_json() + "\n", encoding="utf-8")
    monkeypatch.setattr("docgrain_eval.cli.PublishedAPI", lambda _: api)
    assert main(["run", "--questions", str(path), "--workspace", "ws_local", "--api",
                 "https://example.test", "--dry-run"]) == 0
    assert "context:" in capsys.readouterr().out


def test_table_found_wrong_missing():
    snapshot = {"evidence": [{"id": "e1", "locator": {"page_number": 3}}],
                "structure": [{"id": "t1", "kind": "table", "caption": "Fiyatlar",
                               "annotation": {"provenance": {"evidence_ids": ["e1"]}},
                               "rows": [[{"value": "Oda"}, {"value": "Fiyat"}],
                                        [{"value": "Suit"}, {"value": "100 €"}]]}]}
    base = {"id": "f1", "document_id": "d1", "page": 3, "table_hint": "Fiyatlar",
            "row_label": "Suit", "column_label": "Fiyat", "expected": "100 €"}
    assert check_fact(TableFact.model_validate(base), snapshot)["status"] == "found"
    assert check_fact(TableFact.model_validate(base | {"expected": "200 €"}), snapshot)["status"] == "wrong"
    assert check_fact(TableFact.model_validate(base | {"page": 4}), snapshot)["status"] == "missing"


def test_compare_flips(tmp_path, capsys):
    for name, correct_value in (("a", False), ("b", True)):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "results.jsonl").write_text(
            json.dumps({"id": "q1", "correct": correct_value}) + "\n", encoding="utf-8")
    assert main(["compare", str(tmp_path / "a"), str(tmp_path / "b")]) == 0
    assert "q1: wrong -> correct" in capsys.readouterr().out
