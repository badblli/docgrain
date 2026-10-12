"""Offline 800-record cost comparison; fake HTTP answers, no network or private data."""

import json
from dataclasses import asdict

import httpx
from docgrain_records.match import PairClient, propose_matches
from docgrain_records.match_runner import MatchStats
from docgrain_records.models import ExtractionResult, RoomType


def synthetic_workspace():
    documents = []
    for doc in range(8):
        document = f"document-{doc}"
        records = []
        for item in range(100):
            # Unique alphabetic tokens avoid accidental numeric/generic-word blocks.
            token = "item" + chr(97 + item // 26) + chr(97 + item % 26)
            name = token if item < 90 else token + " variant" + chr(97 + doc)
            records.append(RoomType(id=f"{document}:{item}", name={
                "value": name, "lang": "en", "evidence": [{
                    "document_id": document, "locator": "§1", "quote": name,
                }],
            }))
        documents.append(ExtractionResult(document_id=document, lang="en", records=records))
    return documents


def fake_response(request):
    payload = json.loads(request.content)
    data = json.loads(payload["messages"][1]["content"])
    answer = ({"decisions": [{"id": pair["id"], "decision": "same"}
                             for pair in data["untrusted_pairs"]]}
              if "untrusted_pairs" in data else {"decision": "same"})
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})


def measure():
    results = synthetic_workspace()
    report = {"input_records": 800, "unblocked_cross_document_pairs": 280000}
    outputs = []
    for label, batch_size, concurrency in (("single_pair", 1, 1), ("batched", 8, 4)):
        stats = MatchStats()
        client = PairClient("https://model.example/v1", "fake", "fake-key",
                            transport=httpx.MockTransport(fake_response))
        try:
            matches = propose_matches(results, client, batch_size=batch_size,
                                      concurrency=concurrency, stats=stats)
        finally:
            client.close()
        report[label] = {**asdict(stats), "candidate_counts": matches.candidate_counts}
        outputs.append(matches)
    if outputs[0] != outputs[1]:
        raise AssertionError("batching changed proposals")
    report["identical_proposals"] = True
    return report


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))
