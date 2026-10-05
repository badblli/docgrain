import json
from types import SimpleNamespace

import pytest
from docgrain_eval.cli import _result, main, summarize
from docgrain_eval.scoring import correct, normalize_answer, rescore, time_range

from tests.unit.test_evaluation import question


@pytest.mark.parametrize("separator", ["-", "–", "—", "ile", "ila", " to "])
@pytest.mark.parametrize("closing", ["24:00", "00:00", "24.00", "00.00"])
def test_time_formats(separator, closing):
    assert correct(question("time_range", "09:00-00:00"),
                   {"answer": f"09.00 {separator} {closing}"})


@pytest.mark.parametrize("separator", ["-", "–", "—", "ile", "ila", "to"])
def test_text_and_list_ranges(separator):
    assert correct(question(expected="24-27 m²"), {"answer": f"24 {separator} 27 m²"})
    assert correct(question(expected="4-12 yaş"), {"answer": f"4 {separator} 12 yaş"})
    assert correct(question("list", ["24-27 m²", "4-12 yaş"]),
                   {"answer": f"24 {separator} 27 m²; 4 {separator} 12 yaş"})
    assert not correct(question(expected="24-27 m²"), {"answer": f"24 {separator} 28 m²"})


def test_normalization_keeps_words_and_accept_forms():
    assert normalize_answer("Wi-Fi ile plaj") == "wi-fi ile plaj"
    assert correct(question(expected="çocuk kulübü", accept=["4-12 yaş"]),
                   {"answer": "4 ila 12 yaş"})
    assert correct(question(expected="00:00"), {"answer": "24.00"})


@pytest.mark.parametrize("value", [
    {"total_area": 32000, "unit": "m²"},
    {"total_area": "32.000", "unit": "metrekare"},
    {"value": 32000, "other": 2, "unit": "m²"},
    {"amount": 32000, "other": 2, "unit": "m²"},
])
def test_structured_number(value):
    assert correct(question("number", {"value": 32000, "unit": "m²"}), {"value": value})


@pytest.mark.parametrize("value", [None, {}, {"label": "alan"}, {"a": 3, "b": 4}])
def test_number_answer_fallback(value):
    assert correct(question("number", {"value": 32000, "unit": "m²"}),
                   {"value": value, "answer": "Alan: 32.000 m²"})


@pytest.mark.parametrize("word", ["toplam", "total"])
@pytest.mark.parametrize("value", [None, "", {}])
def test_number_answer_prefers_total(value, word):
    assert correct(question("number", {"value": 7}),
                   {"value": value,
                    "answer": f"3 standart, 4 deluxe olmak üzere {word} 7 oda"})
    assert not correct(question("number", {"value": 3}),
                       {"value": value,
                        "answer": f"3 standart, 4 deluxe olmak üzere {word} 7 oda"})


def test_number_answer_prefers_expected_unit_without_total():
    assert correct(question("number", {"value": 25, "unit": "m²"}),
                   {"value": None, "answer": "3 oda; alan 25 m²"})
    assert not correct(question("number", {"value": 3, "unit": "m²"}),
                       {"value": None, "answer": "3 oda; alan 25 m²"})


def test_number_answer_keeps_first_without_signal():
    assert correct(question("number", {"value": 3}),
                   {"value": None, "answer": "3 oda ve 4 yatak"})


def test_structured_number_rejects_wrong_value_and_unit():
    q = question("number", {"value": 32000, "unit": "m²"})
    assert not correct(q, {"value": {"total_area": 32000, "unit": "m"}})
    assert not correct(q, {"value": {"a": 32000, "b": 4}})
    assert not correct(q, {"value": {"total_area": 12}, "answer": "32000 m²"})


@pytest.mark.parametrize("keys", [("opening_time", "closing_time"), ("open", "close"),
                                  ("start_time", "end_time")])
def test_structured_time(keys):
    assert correct(question("time_range", "23:30-02:00"),
                   {"value": dict(zip(keys, ["23.30", "02:00"], strict=True))})


def test_time_range_with_ile():
    assert time_range("21:30 ile 06:00") == "21:30-06:00"
    assert correct(question("time_range", "21:30-06:00"),
                   {"answer": "21:30 ile 06:00"})


@pytest.mark.parametrize("value", ["unknown", {}, {"opening_time": "23:30"},
                                  {"opening_time": "25:00", "closing_time": "02:00"}])
def test_time_answer_fallback(value):
    assert correct(question("time_range", "23:30-02:00"),
                   {"value": value, "answer": "23:30 - 02:00"})


@pytest.mark.parametrize("value", ["24:01-02:00", "25:00-02:00", "09:60-02:00", "unknown"])
def test_invalid_times(value):
    assert time_range(value) is None
    assert not correct(question("time_range", "09:00-02:00"), {"answer": value})
    assert not correct(question("time_range", "unknown"), {"answer": value})


def test_conflict_ranges_match_every_item():
    q = question("text", [{"value": "09:00-00:00", "document_id": "d1"},
                          {"value": "10:00-18:00", "document_id": "d2"}], difficulty="conflict")
    assert correct(q, {"answer": "Kaynak A: 09.00 ila 24.00; Kaynak B: 10:00 — 18:00"})
    assert not correct(q, {"answer": "Kaynak A: 09:00-24:00"})
    assert not correct(q, {"answer": "09:00-24:00; 10:00-19:00"})


def test_conflict_closing_time_is_not_all_day_operation():
    q = question("text", [{"value": "00:00", "document_id": "d1"},
                          {"value": "24 saat", "document_id": "d2"}], difficulty="conflict")
    assert not correct(q, {"answer": "Kaynak A: 24:00; Kaynak B: gece yarısında kapanır"})
    assert correct(q, {"answer": "Kaynak A: 24.00; Kaynak B: 24 saat açık"})


def test_abstention_unchanged():
    assert correct(question("unanswerable", None), {"abstained": True})
    assert not correct(question("unanswerable", None), {"answer": "bilmiyorum"})
    assert not correct(question(expected="4-12 yaş"), {"answer": "4 ila 12 yaş", "abstained": True})
    assert not correct(question(), None)


def stored_run(tmp_path):
    q = question("time_range", "09:00-00:00")
    questions = tmp_path / "questions.jsonl"
    questions.write_text(q.model_dump_json() + "\n", encoding="utf-8")

    class StoredChat:
        def complete(self, messages):
            return "stored", {"value": "09:00 - 24:00", "abstained": False}, {"total_tokens": 7}

    row = _result(q, "synthetic context", StoredChat())
    row["correct"] = False
    (tmp_path / "results.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    original_summary = summarize([row], "synthetic context", {"d1": "r1"}, "test-model")
    (tmp_path / "summary.json").write_text(json.dumps(original_summary), encoding="utf-8")
    return questions, row, original_summary


def test_rescore_offline_preserves_original_and_metadata(tmp_path, monkeypatch):
    questions, row, original_summary = stored_run(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("rescore must not access APIs or models")

    monkeypatch.setattr("docgrain_eval.cli.ChatClient", forbidden)
    monkeypatch.setattr("docgrain_eval.cli.PublishedAPI", forbidden)
    monkeypatch.setattr("httpx.Client", forbidden)
    assert main(["rescore", str(tmp_path), "--questions", str(questions)]) == 0
    output = tmp_path / "rescored"
    result = json.loads((output / "results.jsonl").read_text(encoding="utf-8"))
    assert result == row | {"correct": True}
    assert json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8")) == row
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["overall"] == {"count": 1, "correct": 1, "accuracy": 1.0}
    for group in ("per_category", "per_difficulty", "per_document"):
        assert all(rate["correct"] == 1 for rate in summary[group].values())
    for key in ("model", "revisions", "context_characters", "context_tokens_approx", "usage",
                "latency_p50_seconds", "latency_p95_seconds", "abstention_recall"):
        assert summary[key] == original_summary[key]
    assert "1/1 (100.0%)" in (output / "summary.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("case", ["duplicate", "unknown", "invalid_parsed"])
def test_rescore_invalid_input_writes_nothing(tmp_path, case):
    questions, row, _ = stored_run(tmp_path)
    rows = [row]
    if case == "duplicate":
        rows.append(row)
    elif case == "unknown":
        row["id"] = "unknown"
    else:
        row["parsed"] = []
    (tmp_path / "results.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in rows), encoding="utf-8")
    with pytest.raises(ValueError):
        rescore(SimpleNamespace(run_dir=tmp_path, questions=questions))
    assert not (tmp_path / "rescored").exists()
