"""Format-only repair and independent repeat measurement, entirely offline."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import docgrain_access.ask as ask_module
import pytest
import test_u1_try
from docgrain_access.ask import AskResult, ModelTimeout, ask_result
from docgrain_api import try_ai
from docgrain_api.ai_access import AIAccess
from docgrain_api.records_repository import RecordsRepository
from test_ai_clients import FakeModel, invocation
from test_u1_try import PATH, room_revision

setup = test_u1_try.setup

spec = importlib.util.spec_from_file_location("dene_abstain", Path("benchmarks/dene_abstain.py"))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


@pytest.fixture
def access(tmp_path):
    store = RecordsRepository(tmp_path)
    store.publish(room_revision())
    return AIAccess(store, "workspace-example")


def room_answer(access):
    data = access.call("get_record", {"collection": "rooms", "id": "rec-room"})
    sources = {s["quote"]: s["id"] for s in data["sources"]}
    return f"32 m² [{sources['32']}]. 2 kişi [{sources['2']}].", sources


@pytest.mark.parametrize("connector", ["İşte yanıt.", "Bilgiler şöyle:", "Kaynaklara göre:"])
def test_uncited_connective_rewritten_once_without_new_tools(access, connector):
    answer, _ = room_answer(access)
    model = FakeModel([invocation(), {"content": connector + "\n" + answer}, {"content": answer}])
    result = ask_result("Bahçe Odası kaç metrekare ve kaç kişilik?", access, model)
    assert not result.abstained and result.answer == answer
    assert {s["quote"] for s in result.sources} == {"32", "2"}
    assert len(model.calls) == 3 and model.calls[-1][1] == []
    messages = model.calls[-1][0]
    assert sum(m["role"] == "tool" for m in messages) == 1
    assert messages[-2] == {"role": "assistant", "content": connector + "\n" + answer}
    assert "untrusted DATA" in messages[-1]["content"]


@pytest.mark.parametrize("fact", [
    "Ücretsizdir.", "Odanın adı Deniz Odası.", "Kapasitesi 3 kişidir.",
    "Saat 08:00'de açılır.", "2 kişiliktir.", "İşte yanıt: fiyat ücretsizdir.",
])
def test_uncited_fact_never_reaches_rewrite_even_if_value_was_read(access, fact):
    answer, _ = room_answer(access)
    model = FakeModel([invocation(), {"content": fact + "\n" + answer}])
    result = ask_result("Oda?", access, model)
    assert result.abstained and result.sources == [] and len(model.calls) == 2


@pytest.mark.parametrize("mutation", [
    lambda answer, ids: answer.replace("32", "36"),
    lambda answer, ids: "Deniz Odası " + answer,
    lambda answer, ids: answer.replace("2 kişi", "2 kişi değildir"),
    lambda answer, ids: answer.replace(ids["32"], ids["2"]),
    lambda answer, ids: answer + " Ücretsizdir [" + ids["32"] + "].",
    lambda answer, ids: answer + " 08:00 [" + ids["32"] + "].",
    lambda answer, ids: answer + " Ek bilgi [src_invented].",
    lambda answer, ids: answer + " Atıfsız cümle.",
    lambda answer, ids: "Bilmiyorum.",
    lambda answer, ids: "",
    lambda answer, ids: None,
])
def test_rewrite_cannot_change_facts_sources_or_weaken_sentence_check(access, mutation):
    answer, ids = room_answer(access)
    model = FakeModel([invocation(), {"content": "İşte yanıt. " + answer},
                       {"content": mutation(answer, ids)}])
    result = ask_result("Oda?", access, model)
    assert result.abstained and result.sources == [] and len(model.calls) == 3


def test_rewrite_cannot_cite_unread_real_source_or_make_new_tool_calls(access):
    answer, ids = room_answer(access)

    class OnlySize:
        def specs(self):
            return access.specs()

        def call(self, name, arguments):
            data = access.call(name, arguments)
            data["sources"] = [s for s in data["sources"] if s["quote"] == "32"]
            return data

    size_answer = answer.split(". ")[0] + "."
    for rewritten in ({"content": answer}, invocation()):
        model = FakeModel([invocation(), {"content": "İşte yanıt. " + size_answer}, rewritten])
        assert ask_result("Oda?", OnlySize(), model).abstained
        assert len(model.calls) == 3 and model.calls[-1][1] == []
    # Invalid source in the original answer must not be laundered by repair.
    model = FakeModel([invocation(), {"content": "İşte yanıt. " + answer}])
    assert ask_result("Oda?", OnlySize(), model).abstained
    assert len(model.calls) == 2 and ids["2"] not in model.calls[-1][0][-1]["content"]


@pytest.mark.parametrize("answer", ["Bilmiyorum.", "İşte yanıt. Bilmiyorum.", "2035 fiyatı 500."])
def test_unknown_question_still_abstains_without_rewrite(access, answer):
    model = FakeModel([invocation(), {"content": answer}])
    result = ask_result("2035 gecelik fiyatı nedir?", access, model)
    assert result.abstained and result.sources == [] and len(model.calls) == 2


def test_repair_stays_within_eight_completion_budget(access):
    answer, _ = room_answer(access)
    model = FakeModel([invocation()] * 7 + [{"content": "İşte yanıt. " + answer}])
    assert ask_result("Oda?", access, model).abstained
    assert len(model.calls) == 8
    model = FakeModel([invocation()] * 6 + [{"content": "İşte yanıt. " + answer}, {"content": answer}])
    assert not ask_result("Oda?", access, model).abstained
    assert len(model.calls) == 8


class ClosingModel(FakeModel):
    closed = False

    def close(self):
        self.closed = True


def test_api_contract_and_pinned_revision_preserved_during_rewrite(setup, monkeypatch):
    client, store, _, _ = setup
    access = AIAccess(store, "workspace-example")
    answer, _ = room_answer(access)

    class PublishingModel(ClosingModel):
        def complete(self, messages, tools):
            if len(self.calls) == 2:
                store.publish(room_revision("r2", capacity=3))
            return super().complete(messages, tools)

    model = PublishingModel([invocation(), {"content": "İşte yanıt. " + answer}, {"content": answer}])
    monkeypatch.setattr(try_ai, "OpenAICompatibleClient", lambda *a, **kw: model)
    response = client.post(PATH, json={"question": "Oda?"})
    result = response.json()
    assert response.status_code == 200 and not result["abstained"]
    assert set(result) == {"answer", "abstained", "workspace_id", "revision_id", "mode", "sources"}
    assert result["revision_id"] == "r1" and result["mode"] == "approved"
    assert result["answer"] == answer and model.closed


def test_rewrite_transport_timeout_remains_api_error(setup, monkeypatch):
    client, store, _, _ = setup
    answer, _ = room_answer(AIAccess(store, "workspace-example"))

    class TimeoutModel(ClosingModel):
        def complete(self, messages, tools):
            if len(self.calls) == 2:
                raise ModelTimeout("private provider output")
            return super().complete(messages, tools)

    model = TimeoutModel([invocation(), {"content": "İşte yanıt. " + answer}])
    monkeypatch.setattr(try_ai, "OpenAICompatibleClient", lambda *a, **kw: model)
    response = client.post(PATH, json={"question": "Oda?"})
    assert response.status_code == 504 and "private provider output" not in response.text
    assert model.closed


QUESTIONS = [{
    "id": "room", "kind": "known", "question": "Bahçe Odası kaç metrekare ve kaç kişilik?",
    "claims": [
        {"pattern": r"32\s*m²", "quote": "32", "document_name": "odalar.txt", "locator": "§1 p.1"},
        {"pattern": r"2\s*kişi", "quote": "2", "document_name": "odalar.txt", "locator": "§1 p.1"},
    ], "forbidden_patterns": [r"\b36\b"],
}, {"id": "price", "kind": "unknown", "question": "2035 gecelik fiyatı nedir?"}]


def test_measurement_repeats_known_unknown_and_scores_independent_sources(access):
    answer, _ = room_answer(access)
    models = []

    def factory():
        responses = ([invocation(), {"content": "İşte yanıt. " + answer}, {"content": answer}]
                     if len(models) % 2 == 0 else [invocation(), {"content": "Bilmiyorum."}])
        model = ClosingModel(responses)
        models.append(model)
        return model

    report = benchmark.measure(QUESTIONS, access, factory, repetitions=5)
    assert report["correct_with_sources"] == report["known_runs"] == report["unknown_runs"] == 5
    assert report["abstained_on_known"] == report["answered_on_unknown"] == report["invented_sources"] == 0
    assert report["passed"] and report["errors"] == 0 and report["abstained_on_known_rate"] == 0
    assert report["revision_id"] == "r1" and len(report["results"]) == 10
    assert all(model.closed for model in models)
    assert "32 m²" not in json.dumps(report)  # No answers or source quotes in report.


def test_paired_fake_measurement_reduces_one_in_five_known_abstentions(access, monkeypatch):
    answer, _ = room_answer(access)

    def run():
        count = 0

        def factory():
            nonlocal count
            count += 1
            if count % 2 == 0:
                responses = [invocation(), {"content": "Bilmiyorum."}]
            elif count == 9:
                responses = [invocation(), {"content": "İşte yanıt. " + answer}, {"content": answer}]
            else:
                responses = [invocation(), {"content": answer}]
            return ClosingModel(responses)

        return benchmark.measure(QUESTIONS, access, factory, repetitions=5)

    with monkeypatch.context() as baseline:
        baseline.setattr(ask_module, "_rewrite_answer", lambda *a: None)
        before = run()
    after = run()
    assert before["correct_with_sources"] == 4 and before["abstained_on_known_rate"] == 0.2
    assert after["correct_with_sources"] == 5 and after["abstained_on_known_rate"] == 0
    assert before["answered_on_unknown"] == after["answered_on_unknown"] == 0
    assert before["invented_sources"] == after["invented_sources"] == 0


def test_measurement_detects_leaked_unread_sources(access, monkeypatch):
    def broken_result(question, trace, model):
        trace.call("get_record", {"collection": "rooms", "id": "rec-room", "mode": "approved"})
        return AskResult("32 m² [src_unread].", False, [{"id": "src_unread", "quote": "32"}])

    monkeypatch.setattr(benchmark, "ask_result", broken_result)
    report = benchmark.measure(QUESTIONS, access, lambda: ClosingModel([]), repetitions=1)
    assert report["invented_sources"] == 2 and report["errors"] == 2 and not report["passed"]
    assert all(row["outcome"] == "invalid_sources" for row in report["results"])


def test_measurement_rejects_revision_drift_as_error(access):
    class DriftingAccess:
        def specs(self):
            return access.specs()

        def call(self, *args):
            return access.call(*args) | {"revision_id": "r2"}

    report = benchmark.measure(QUESTIONS, DriftingAccess(), lambda: ClosingModel([
        invocation(), {"content": "Bilmiyorum."}]), repetitions=1)
    assert report["errors"] == 2 and not report["passed"]
    assert report["abstained_on_known"] == 0


def test_measurement_counts_failure_and_does_not_mistake_citations_for_correctness(access):
    answer, ids = room_answer(access)
    models = iter([
        ClosingModel([invocation(), {"content": "Bilmiyorum."}]),
        ClosingModel([invocation(), {"content": answer}]),
        ClosingModel([invocation(), {"content": answer.replace("32", "36")}]),
        ClosingModel([invocation(), {"content": "Bilmiyorum."}]),
        ClosingModel([invocation(), {"content": answer.replace(ids["32"], ids["2"])}]),
        ClosingModel([invocation(), {"content": "Invented [src_invented]."}]),
    ])
    report = benchmark.measure(QUESTIONS, access, lambda: next(models), repetitions=3)
    assert not report["passed"] and report["abstained_on_known"] == 1
    assert report["incorrect_on_known"] == 2 and report["answered_on_unknown"] == 1
    assert report["invented_sources"] == 0  # Invented attempt rejected by ask_result.
    assert report["abstained_on_known_rate"] == pytest.approx(1 / 3)


def test_measurement_service_errors_are_not_successful_abstentions(access):
    class BrokenModel(ClosingModel):
        def complete(self, messages, tools):
            raise ModelTimeout("private detail")

    report = benchmark.measure(QUESTIONS, access, lambda: BrokenModel([]), repetitions=1)
    assert report["errors"] == 2 and not report["passed"]
    assert report["abstained_on_known"] == report["answered_on_unknown"] == 0
    assert "private detail" not in json.dumps(report)


def test_measurement_cli_off_by_default_even_with_connection_args(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("network client constructed without explicit opt-in")

    monkeypatch.setattr(benchmark, "AccessClient", forbidden)
    monkeypatch.setattr(benchmark, "OpenAICompatibleClient", forbidden)
    assert benchmark.main(["--api-url", "https://api.example", "--base-url", "https://model.example",
                           "--model", "fake", "--workspace", "example"]) == 0
    assert "Model kapalı" in capsys.readouterr().out


def test_live_cli_uses_explicit_connections_and_sanitized_report(access, tmp_path, monkeypatch, capsys):
    answer, _ = room_answer(access)
    key_path = tmp_path / "questions.json"
    key_path.write_text(json.dumps(QUESTIONS, ensure_ascii=False), encoding="utf-8")
    connections = []
    models = iter([ClosingModel([invocation(), {"content": answer}]),
                   ClosingModel([invocation(), {"content": "Bilmiyorum."}])])

    class LocalAccess:
        def __init__(self, *args):
            connections.append(args)

        def specs(self):
            return access.specs()

        def call(self, *args):
            return access.call(*args)

        def close(self):
            connections.append("closed")

    monkeypatch.setattr(benchmark, "AccessClient", LocalAccess)
    monkeypatch.setattr(benchmark, "OpenAICompatibleClient", lambda *a, **kw: next(models))
    assert benchmark.main(["--enable-model", "--api-url", "https://api.example", "--workspace", "example",
                           "--base-url", "https://model.example/v1", "--model", "fake", "--revision", "r1",
                           "--questions", str(key_path), "--repetitions", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] and connections == [("https://api.example", "example", "r1"), "closed"]


@pytest.mark.parametrize("mutation", [
    lambda qs: [], lambda qs: qs[:1], lambda qs: [{**qs[0], "claims": []}, qs[1]],
    lambda qs: [{**qs[0], "claims": [{"pattern": "32"}]}, qs[1]],
])
def test_independent_key_cannot_silently_skip_known_unknown_or_source_provenance(mutation):
    with pytest.raises(ValueError):
        benchmark.validate_questions(mutation(deepcopy(QUESTIONS)))
