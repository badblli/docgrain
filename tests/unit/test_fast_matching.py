"""Synthetic matching coverage, with fake HTTP and no real model/network calls."""

import json
import socket
import time
from dataclasses import asdict
from threading import Barrier, Lock
from types import SimpleNamespace

import httpx
import pytest
from docgrain_records.cli import main
from docgrain_records.match import PairClient, accept_strong_matches, propose_matches
from docgrain_records.match_merge import write_json
from docgrain_records.match_runner import MatchBudgetExceeded, MatchStats
from docgrain_records.model import ModelResponseError
from docgrain_records.models import ExtractionResult, Outlet, RoomType


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("tests must never contact the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def fact(doc, value):
    return {"value": value, "lang": "en", "evidence": [{
        "document_id": doc, "locator": "§1", "quote": str(value),
    }]}


def documents(count=24):
    results = []
    for doc, suffix in (("a", "north"), ("b", "south")):
        records = [RoomType(id=f"{doc}:{item}", name=fact(doc, f"item{chr(97 + item)} {suffix}"))
                   for item in range(count)]
        results.append(ExtractionResult(document_id=doc, lang="en", records=records))
    return results


def update(record, **fields):
    return type(record).model_validate({**record.model_dump(mode="json"), **fields})


def request_pairs(request):
    data = json.loads(json.loads(request.content)["messages"][1]["content"])
    return data.get("untrusted_pairs", [{"id": "single", **data}])


def response(request, decision="same"):
    pairs = request_pairs(request)
    answer = ({"decision": decision} if pairs[0]["id"] == "single" else
              {"decisions": [{"id": pair["id"], "decision": decision} for pair in reversed(pairs)]})
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})


def client(handler=response, model="fake"):
    return PairClient("https://model.example/v1", model, "fake-key",
                      transport=httpx.MockTransport(handler))


def test_blocking_and_rules_preserve_true_matches_and_only_judge_middle():
    results = documents(3)
    results[0].records[0] = update(results[0].records[0], name=fact("a", "İskele-Bar 2"))
    results[1].records[0] = update(results[1].records[0], name=fact("b", "iskele bar 2"))
    results[0].records[1] = update(results[0].records[1], capacity=fact("a", 2))
    results[1].records[1] = update(results[1].records[1], capacity=fact("b", 3))
    # No shared names, but equal independent key fields preserve a translated match.
    results[0].records.append(RoomType(id="a:translated", name=fact("a", "Garden room"),
                                      size_m2=fact("a", 32), capacity=fact("a", 4)))
    results[1].records.append(RoomType(id="b:translated", name=fact("b", "Bahçe odası"),
                                      size_m2=fact("b", 32), capacity=fact("b", 4)))
    for result in results:
        # Same names in distinct collections never form a cross-collection pair.
        result.records.append(Outlet(id=result.document_id + ":outlet",
                                     name=fact(result.document_id, "iskele bar 2")))
    calls = []

    def handler(request):
        calls.extend(request_pairs(request))
        return response(request, "unsure")

    chat = client(handler)
    try:
        matches = propose_matches(results, chat)
    finally:
        chat.close()
    assert len(matches.proposals) == 5
    assert all(p.left.record_type == p.right.record_type for p in matches.proposals)
    assert len(calls) == 1
    assert all("itemc" in r["name"]["value"] for r in calls[0]["untrusted_records"])
    assert sorted(p.decision for p in matches.proposals) == ["different", "same", "same", "same", "unsure"]
    accepted = accept_strong_matches(results, matches)
    assert sum(p.review_state == "accepted" for p in accepted.proposals) == 2


def test_no_shared_token_and_different_keys_are_pruned_without_model():
    results = documents(1)
    results[0].records[0] = update(results[0].records[0], name=fact("a", "North room"))
    results[1].records[0] = update(results[1].records[0], name=fact("b", "South room"))
    for result, number in zip(results, (20, 30), strict=True):
        result.records[0] = update(result.records[0], size_m2=fact(result.document_id, number))
    chat = client(lambda _: pytest.fail("obvious non-match must not reach model"))
    try:
        matches = propose_matches(results, chat)
    finally:
        chat.close()
    assert matches.proposals == []
    assert matches.candidate_counts["room_type"]["pruned_pairs"] == 1


def test_batching_concurrency_and_resume_are_identical(tmp_path):
    results = documents()
    sequential = client()
    try:
        expected = propose_matches(results, sequential, batch_size=1, concurrency=1)
    finally:
        sequential.close()
    barrier, lock = Barrier(4), Lock()
    active = maximum = calls = 0
    batch_lengths = []

    def handler(request):
        nonlocal active, maximum, calls
        payload = json.loads(request.content)
        assert sum(len(m["content"]) for m in payload["messages"]) <= 12000
        assert "untrusted DATA" in payload["messages"][0]["content"]
        with lock:
            active += 1
            maximum = max(active, maximum)
            calls += 1
            number = calls
            batch_lengths.append(len(request_pairs(request)))
        if number <= 4:
            barrier.wait(timeout=5)
        with lock:
            active -= 1
        return response(request)

    chat, stats = client(handler), MatchStats()
    path = tmp_path / "match_progress.jsonl"
    try:
        matches = propose_matches(results, chat, concurrency=4, batch_size=4, batch_chars=12000,
                                  progress_path=path, stats=stats)
        assert maximum == 4 and calls == 6 and batch_lengths == [4] * 6
        assert stats.model_calls == 6
        assert matches == expected
        assert propose_matches(results[::-1], chat, concurrency=1, batch_size=1,
                               progress_path=path, stats=stats) == expected
        assert stats.resumed == 24 and stats.model_calls == 0 and calls == 6
    finally:
        chat.close()
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 24 and all(e["model"] for e in entries)
    assert "untrusted_records" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("names", [("Straße-Bar", "strasse bar"), ("Марина бар", "Marina Bar"),
                                   ("İskele-2", "Iskele 2")])
def test_normalized_identity_across_languages_needs_no_model(names):
    results = documents(1)
    for result, name in zip(results, names, strict=True):
        result.records[0] = update(result.records[0], name=fact(result.document_id, name))
    chat = client(lambda _: pytest.fail("normalized identity must not call a model"))
    try:
        matches = accept_strong_matches(results, propose_matches(results, chat))
    finally:
        chat.close()
    assert matches.proposals[0].review_state == "accepted"
    assert matches.proposals[0].reviewer == "rule:identical-name"


def test_resume_reapplies_global_ambiguity_without_accumulating_signals(tmp_path):
    results = documents(2)
    for result, names in zip(results, (("Garden North", "Garden South"), ("Garden East", "Garden West")),
                             strict=True):
        result.records = [update(r, name=fact(result.document_id, name))
                          for r, name in zip(result.records, names, strict=True)]
    path, chat = tmp_path / "match_progress.jsonl", client()
    try:
        matches = propose_matches(results, chat, progress_path=path)
        assert len(matches.proposals) == 4 and all(p.decision == "unsure" for p in matches.proposals)
        assert propose_matches(results, chat, progress_path=path) == matches
    finally:
        chat.close()
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(e["decision"] == "same" and not any(s["kind"] == "ambiguous" for s in e["signals"])
               for e in entries)


def test_resume_skips_previously_decided_pair_scoring(tmp_path, monkeypatch):
    path, chat = tmp_path / "match_progress.jsonl", client(lambda r: response(r, "different"))
    try:
        expected = propose_matches(documents(2), chat, progress_path=path)
        monkeypatch.setattr("docgrain_records.match._score",
                            lambda *args: pytest.fail("saved pair should not be scored again"))
        assert propose_matches(documents(2), chat, progress_path=path) == expected
    finally:
        chat.close()


def test_budget_checkpoints_then_resumes_with_same_proposals(tmp_path, monkeypatch):
    import docgrain_records.match_runner as runner

    clock = [time.monotonic()]
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    reports = []

    def handler(request):
        clock[0] += 21
        return response(request)

    chat, stats = client(handler), MatchStats()
    path, results = tmp_path / "match_progress.jsonl", documents(6)
    try:
        with pytest.raises(MatchBudgetExceeded):
            propose_matches(results, chat, batch_size=2, concurrency=1, max_minutes=.1,
                            progress_path=path, stats=stats, progress=lambda s: reports.append(asdict(s)))
        assert stats.decided == 2 and stats.model_calls == 1
        assert any(r["elapsed"] >= 20 and r["decided"] == 2 for r in reports)
        resumed = propose_matches(results, chat, batch_size=2, concurrency=1,
                                  progress_path=path, stats=stats)
        assert stats.resumed == 2 and stats.model_calls == 2
        assert resumed == propose_matches(results, chat, batch_size=1)
    finally:
        chat.close()


def test_failed_batch_preserves_successful_sibling_and_retries_only_undecided(tmp_path):
    barrier = Barrier(2)
    calls = []

    def handler(request):
        pairs = request_pairs(request)
        calls.append(pairs)
        barrier.wait(timeout=5)
        if "itema" in pairs[0]["untrusted_records"][0]["name"]["value"]:
            return httpx.Response(200, json={"choices": [{"message": {"content": "invalid"}}]})
        return response(request)

    chat, path = client(handler), tmp_path / "match_progress.jsonl"
    try:
        with pytest.raises(ModelResponseError):
            propose_matches(documents(4), chat, concurrency=2, batch_size=2, progress_path=path)
    finally:
        chat.close()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    stats, chat = MatchStats(), client()
    try:
        actual = propose_matches(documents(4), chat, progress_path=path, stats=stats)
        assert stats.resumed == 2 and stats.model_calls == 1
        assert actual == propose_matches(documents(4), chat)
    finally:
        chat.close()


def test_resume_discards_torn_tail_and_invalidates_changed_input_or_model(tmp_path):
    path, results = tmp_path / "match_progress.jsonl", documents(2)
    stats, chat = MatchStats(), client()
    try:
        expected = propose_matches(results, chat, progress_path=path)
        with path.open("ab") as stream:
            stream.write(b'{"partial":')
        assert propose_matches(results, chat, progress_path=path, stats=stats) == expected
        assert stats.resumed == 2 and stats.model_calls == 0
        results[0].records[0].name.evidence[0].locator = "§2"
        propose_matches(results, chat, progress_path=path, stats=stats)
        assert stats.resumed == 0 and stats.model_calls == 1
        chat.model = "different-model"
        propose_matches(results, chat, progress_path=path, stats=stats)
        assert stats.resumed == 0 and stats.model_calls == 1
        # Offline results must not inherit saved model decisions.
        offline = propose_matches(results, progress_path=path, stats=stats)
        assert stats.resumed == 0 and all(p.decision == "unsure" for p in offline.proposals)
    finally:
        chat.close()
    path.write_text('{"bad":"PRIVATE SOURCE"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid match progress entry"):
        propose_matches(results, progress_path=path)


@pytest.mark.parametrize("bad", ["missing", "duplicate", "unknown", "invalid"])
def test_batch_ids_and_decisions_are_strictly_validated(bad):
    def handler(request):
        ids = [p["id"] for p in request_pairs(request)]
        decisions = [{"id": pair_id, "decision": "same"} for pair_id in ids]
        if bad == "missing":
            decisions.pop()
        elif bad == "duplicate":
            decisions[1]["id"] = decisions[0]["id"]
        elif bad == "unknown":
            decisions[1]["id"] = "unknown"
        else:
            decisions[1]["decision"] = "accept all"
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps({"decisions": decisions}),
        }}]})
    chat = client(handler)
    try:
        with pytest.raises(ModelResponseError, match="valid pair decision batch"):
            propose_matches(documents(2), chat)
    finally:
        chat.close()


def test_retries_429_5xx_timeout_and_compatible_format_fallback(monkeypatch):
    monkeypatch.setattr("docgrain_records.model.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(429)
        if len(calls) == 2:
            return httpx.Response(503)
        if len(calls) == 3:
            raise httpx.ReadTimeout("fake", request=request)
        if len(calls) == 4:
            return httpx.Response(400)
        return response(request)

    chat, stats = client(handler), MatchStats()
    try:
        actual = propose_matches(documents(2), chat, stats=stats)
    finally:
        chat.close()
    assert stats.model_calls == 5 and all(p.decision == "same" for p in actual.proposals)
    assert "response_format" not in calls[-1]


def test_prompt_bound_splits_batches_and_rejects_oversized_pair(tmp_path):
    requests = []

    def handler(request):
        messages = json.loads(request.content)["messages"]
        requests.append(messages)
        assert sum(len(m["content"]) for m in messages) <= 2500
        return response(request)

    chat = client(handler)
    try:
        matches = propose_matches(documents(6), chat, batch_size=6, batch_chars=2500)
        assert len(requests) > 1 and len(matches.proposals) == 6
        results = documents(1)
        results[0].records[0].name.evidence[0].quote = "Untrusted source text " * 200
        with pytest.raises(ValueError, match="exceeds --batch-chars"):
            propose_matches(results, chat, batch_chars=2500,
                            progress_path=tmp_path / "match_progress.jsonl")
    finally:
        chat.close()


def test_cli_budget_has_no_partial_final_file_and_can_resume(tmp_path, monkeypatch, capsys):
    import docgrain_records.match_runner as runner

    results, root, out = documents(6), tmp_path / "in", tmp_path / "out"
    for result in results:
        write_json(root / result.document_id / "records.json", result.model_dump(mode="json"))
    clock = [time.monotonic()]
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def handler(request):
        clock[0] += 21
        return response(request)

    monkeypatch.setattr("docgrain_records.cli.PairClient", lambda *args: client(handler))
    monkeypatch.setenv("MATCH_FAKE_KEY", "fake-key")
    argv = ["match", "--records", str(root), "--out", str(out), "--base-url", "https://model.example/v1",
            "--model", "fake", "--api-key-env", "MATCH_FAKE_KEY", "--concurrency", "1", "--batch-size", "2"]
    assert main([*argv, "--max-minutes", ".1"]) == 2
    assert (out / "match_progress.jsonl").exists()
    assert not (out / "match_proposals.json").exists()
    assert not (out / "match_summary.json").exists()
    assert "Süre doldu" in capsys.readouterr().err
    assert main(argv) == 0
    saved = json.loads((out / "match_proposals.json").read_text(encoding="utf-8"))
    chat = client()
    try:
        assert saved == propose_matches(results, chat).model_dump(mode="json")
    finally:
        chat.close()
    assert "2 çift önceki çalışmadan" in capsys.readouterr().err
