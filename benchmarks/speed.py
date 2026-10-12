"""Opt-in WP113 speed/accuracy comparison. All output excludes prompts, answers and keys.

The default option is measured with the old extraction plan and prose lists. Candidates
use grouped extraction and server lists. A passing synthetic gate is necessary, never
sufficient: the lead also compares the real independent field key before enabling them.
"""

import argparse
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for package in ("domain", "evaluation", "records", "access"):
    sys.path.insert(0, str(ROOT / "packages" / package))
sys.path.insert(0, str(ROOT / "benchmarks"))

from dene_abstain import measure, validate_questions
from docgrain_access.ask import OpenAICompatibleClient
from docgrain_access.client import AccessClient
from docgrain_records.extractor import extract
from docgrain_records.model import ChatClient
from docgrain_records.models import ExtractionUsage

CONTEXT = """[§1 p.1]
# Garden room
Name: Garden room
Capacity: 2 people
Size: 32 m²

[§2 p.2]
# Indoor pool
Name: Indoor pool
Kind: pool
Opening hours: 08:00–20:00

[§3 p.3]
# Pets policy
Name: Pets
Pets are not allowed.
"""
KEY = {("room_type", "Garden room"): {"name": "Garden room", "capacity": 2, "size_m2": 32},
       ("facility", "Indoor pool"): {"name": "Indoor pool", "kind": "pool", "hours": "08:00–20:00"},
       ("policy", "Pets"): {"name": "Pets", "text": "Pets are not allowed."}}
TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens")


def latency(values):
    return {"p50": statistics.median(values),
            "p95": sorted(values)[math.ceil(len(values) * .95) - 1], "max": max(values)}


def usage_summary(calls):
    output = {"requests": len(calls), "retries": sum(call["attempt"] > 1 for call in calls)}
    for key in TOKEN_KEYS:
        reported = [call[key] for call in calls if call.get(key) is not None]
        output[key] = sum(reported) if reported else None
        output["missing_" + key + "_calls"] = len(calls) - len(reported)
    return output


def score_extraction(result):
    """Independent, fixed fixture key; missing fields and extras are counted separately."""
    actual = {}
    duplicates = 0
    for record in result.records:
        key = (record.type, record.name.value)
        duplicates += key in actual
        actual[key] = {field: fact.value for field in type(record).model_fields
                       if (fact := getattr(record, field)) is not None and hasattr(fact, "evidence")}
    expected = sum(len(fields) for fields in KEY.values())
    correct = sum(actual.get(key, {}).get(field) == value
                  for key, fields in KEY.items() for field, value in fields.items())
    extras = sum(field not in KEY.get(key, {}) for key, fields in actual.items() for field in fields)
    return {"field_accuracy": 100 * correct / expected, "correct_fields": correct,
            "expected_fields": expected, "extra_fields": extras, "duplicate_records": duplicates,
            "rejected_fields": len(result.rejected), "failed_sections": len(result.failures)}


def measure_extraction(factory, *, repetitions=3, grouped=False, concurrency=6):
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    results, seconds, calls = [], [], []
    for repetition in range(repetitions):
        chat = factory()
        usage = ExtractionUsage()
        started = time.monotonic()
        try:
            result = extract(CONTEXT, "doc_speed_fixture", "en", chat, usage=usage,
                             grouped_passes=grouped, concurrency=concurrency)
            score = score_extraction(result)
        finally:
            chat.close()
        duration = time.monotonic() - started
        requests = [call.model_dump(mode="json", exclude_none=True) for call in usage.calls]
        seconds.append(duration)
        calls.extend(requests)
        results.append({"repetition": repetition + 1, "seconds": duration, **score, "calls": requests})
    return {"latency_seconds": latency(seconds), "usage": usage_summary(calls), "results": results,
            "field_accuracy": statistics.fmean(row["field_accuracy"] for row in results)}


def extraction_client(base_url, model, key, timeout, options):
    chat = ChatClient(base_url, model, key or "local-profile", timeout=timeout, **options)
    if not key:
        del chat.client.headers["Authorization"]
    return chat


def gates(baseline, candidate):
    dene = candidate["dene"]
    extraction = candidate["extraction"]
    return {"dene": dene["passed"] and dene["correct_with_sources"] >= baseline["dene"]["correct_with_sources"],
            "extraction": extraction["field_accuracy"] >= baseline["extraction"]["field_accuracy"] - 1
            and all(not any(row[key] for key in ("extra_fields", "duplicate_records", "failed_sections"))
                    for row in extraction["results"]),
            "real_independent_key": "not_verified"}


def stage_table(job):
    stages = job.get("speed", job.get("metadata", {}).get("speed", {})).get("stages", {})
    if not stages:
        raise ValueError("stage measurements unavailable")
    header = "| Aşama | Saniye | Çağrı | Tekrar | Girdi | Çıktı | Düşünme |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    names = {"structure": "Tabloları oku", "discover": "Listeleri bul", "accept_schema": "Yapıyı kontrol et", "extract": "Bilgileri çıkar",
             "match": "Karşılaştır", "merge": "Birleştir", "publish": "Yayınla"}
    rows = []
    for stage, label in names.items():
        values = stages.get(stage)
        if values is not None:
            rows.append("| " + label + " | " + " | ".join(
                "—" if values.get(key) is None else str(round(values[key], 3))
                for key in ("wall_seconds", "calls", "retries", "prompt_tokens", "completion_tokens", "reasoning_tokens")) + " |")
    return header + "\n" + "\n".join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-model", action="store_true")
    for name in ("api-url", "workspace", "revision", "base-url", "model", "api-key-env"):
        parser.add_argument("--" + name)
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--job-report", type=Path, help="GET record-jobs result; render its numeric stage table")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--efforts", nargs="+", choices=["default", "none", "minimal", "low", "medium", "high"],
                        default=["default", "none", "low", "medium"])
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--model-timeout", type=float, default=60)
    parser.add_argument("--extraction-timeout", type=float, default=180)
    parser.add_argument("--question-timeout", type=float, default=120)
    args = parser.parse_args(argv)
    if args.job_report:
        try:
            print(stage_table(json.loads(args.job_report.read_text(encoding="utf-8-sig"))))
            return 0
        except (OSError, ValueError, TypeError, KeyError):
            print("Aşama ölçümleri okunamadı.", file=sys.stderr)
            return 1
    if not args.enable_model:
        print("Model kapalı. Ölçüm için --enable-model ve bağlantı bilgilerini açıkça verin.")
        return 0
    if not all((args.api_url, args.workspace, args.base_url, args.model, args.questions)):
        parser.error("--api-url, --workspace, --base-url, --model ve --questions gerekli")
    if (args.repetitions < 1 or not 1 <= args.concurrency <= 32
            or args.max_tokens is not None and args.max_tokens < 1
            or min(args.model_timeout, args.question_timeout, args.extraction_timeout) <= 0):
        parser.error("Tekrar, eşzamanlı istek sayısı, süre ve yanıt sınırlarını kontrol edin")
    key = os.environ.get(args.api_key_env) if args.api_key_env else ""
    if key is None:
        parser.error("Belirtilen anahtar profili hazır değil")
    access = None
    try:
        questions = validate_questions(json.loads(args.questions.read_text(encoding="utf-8-sig")))
        if {item["kind"] for item in questions} != {"known", "list", "unknown"}:
            raise ValueError("single/list/unknown set required")
        access = AccessClient(args.api_url, args.workspace, args.revision)
        # Resolve/pin once, then share this immutable publication across option sets.
        access.specs()
        report = {"options": [], "default_changed": False}
        for label in ["baseline", *args.efforts]:
            effort = None if label in {"baseline", "default"} else label
            optimized = label != "baseline"
            options = {"reasoning_effort": effort, "max_tokens": args.max_tokens if optimized else None}
            row = {"option": label, "settings": {**options, "concurrency": args.concurrency,
                                                  "grouped_passes": optimized, "render_lists": optimized}}
            try:
                dene = measure(questions, access, lambda options=options: OpenAICompatibleClient(
                    args.base_url, args.model, key, timeout=args.model_timeout,
                    total_timeout=args.question_timeout, **options), repetitions=args.repetitions,
                    question_timeout=args.question_timeout, render_lists=optimized)
                dene["usage"] = usage_summary([call for result in dene["results"] for call in result["calls"]])
                extraction = measure_extraction(lambda options=options: extraction_client(
                    args.base_url, args.model, key, args.extraction_timeout, options),
                    repetitions=args.repetitions, grouped=optimized,
                    concurrency=args.concurrency)
                row.update(dene=dene, extraction=extraction, status="measured")
                if optimized and report["options"][0].get("status") == "measured":
                    row["gates"] = gates(report["options"][0], row)
            except Exception:  # noqa: BLE001 -- Never print provider/source/credential errors.
                row["status"] = "failed_or_unsupported"
            report["options"].append(row)
        output = json.dumps(report, ensure_ascii=False, indent=2)
        if key and key in output:
            raise ValueError("credential reflection")
        print(output)
        return 0 if all(row.get("gates", {"dene": False, "extraction": False})["dene"]
                        and row.get("gates", {"extraction": False})["extraction"]
                        for row in report["options"][1:]) else 1
    except Exception:  # noqa: BLE001 -- No private paths/config/source/transport output.
        print("Ölçüm tamamlanamadı; bağlantıyı ve bağımsız anahtarı kontrol edin.", file=sys.stderr)
        return 1
    finally:
        if access is not None:
            access.close()


if __name__ == "__main__":
    raise SystemExit(main())
