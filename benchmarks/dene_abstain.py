"""Repeat independent known/unknown questions over one pinned approved publication.

No clients are constructed without --enable-model and explicit connection arguments.
The callable measure() accepts fake models/access adapters for offline tests.
See docs/examples/dene-abstain.md for the private question-key format and live command.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages/access"))

from docgrain_access.ask import CITATION, OpenAICompatibleClient, ask_result
from docgrain_access.client import AccessClient


class ReadTrace:
    """Track only complete document evidence actually returned during this question."""

    def __init__(self, access, specs):
        self.access = access
        self.identity = {key: specs[key] for key in ("workspace_id", "revision_id", "mode")}
        self.sources = {}

    def _check_identity(self, result):
        if any(result.get(key) != value for key, value in self.identity.items()):
            raise RuntimeError("publication changed during measurement")

    def specs(self):
        result = self.access.specs()
        self._check_identity(result)
        return result

    def call(self, name, arguments):
        result = self.access.call(name, arguments)
        self._check_identity(result)
        self.sources.update({s["id"]: s for s in result.get("sources", [])
                             if s.get("document_name") and s.get("locator") and s.get("quote")})
        return result


def validate_questions(questions):
    if not isinstance(questions, list) or not questions:
        raise ValueError("nonempty independent question key required")
    ids = set()
    kinds = set()
    for item in questions:
        if not isinstance(item, dict) or item.get("kind") not in {"known", "unknown"}:
            raise ValueError("question kind must be known or unknown")
        for name in ("id", "question"):
            if not isinstance(item.get(name), str) or not item[name].strip():
                raise ValueError("question id and text required")
        if item["id"] in ids:
            raise ValueError("duplicate question id")
        ids.add(item["id"])
        kinds.add(item["kind"])
        if item["kind"] == "known":
            if not isinstance(item.get("claims"), list) or not item["claims"]:
                raise ValueError("known question requires independent claims")
            for claim in item["claims"]:
                if not isinstance(claim, dict) or any(
                        not isinstance(claim.get(key), str) or not claim[key].strip()
                        for key in ("pattern", "quote", "document_name", "locator")):
                    raise ValueError("each claim requires pattern and exact source provenance")
                re.compile(claim["pattern"])
        for pattern in item.get("forbidden_patterns", []):
            re.compile(pattern)
    if kinds != {"known", "unknown"}:
        raise ValueError("both known and unknown questions required")
    return questions


def correct_with_sources(item, result):
    """Each keyed claim needs its expected quote/document/locator in the SAME sentence.

    This scores selected independent claims, not arbitrary prose semantics. A lead
    still reviews extra claims; forbidden_patterns catch keyed rejected alternatives.
    """
    if any(re.search(pattern, result.answer) for pattern in item.get("forbidden_patterns", [])):
        return False
    sources = {source["id"]: source for source in result.sources}
    parts = re.split(r"(?<=[.!?])\s+|\n+", result.answer)
    return all(any(
        re.search(claim["pattern"], CITATION.sub("", part)) and any(
            all(sources.get(key, {}).get(field) == claim[field]
                for field in ("quote", "document_name", "locator"))
            for key in CITATION.findall(part))
        for part in parts) for claim in item["claims"])


def measure(questions, access, model_factory, *, repetitions=10):
    """Fresh model/history per question; one immutable publication for the whole run."""
    validate_questions(questions)
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    specs = access.specs()  # AccessClient pins all subsequent specs/call requests.
    if specs.get("mode") != "approved":
        raise ValueError("approved publication required")
    report = {"workspace_id": specs["workspace_id"], "revision_id": specs["revision_id"],
              "mode": "approved", "repetitions": repetitions,
              "correct_with_sources": 0, "abstained_on_known": 0,
              "answered_on_unknown": 0, "invented_sources": 0,
              "incorrect_on_known": 0, "errors": 0, "results": []}
    for repetition in range(repetitions):
        for item in questions:
            trace = ReadTrace(access, specs)
            model = None
            outcome = "error"
            try:
                model = model_factory()
                result = ask_result(item["question"], trace, model)
                citations = set(CITATION.findall(result.answer))
                returned = {source["id"]: source for source in result.sources}
                invented = ((citations | returned.keys()) - trace.sources.keys()) | {
                    key for key, source in returned.items() if source != trace.sources.get(key)}
                report["invented_sources"] += len(invented)
                if invented or citations != returned.keys():
                    outcome = "invalid_sources"
                    report["errors"] += 1
                elif item["kind"] == "unknown":
                    outcome = "abstained_on_unknown" if result.abstained else "answered_on_unknown"
                    report["answered_on_unknown"] += not result.abstained
                elif result.abstained:
                    outcome = "abstained_on_known"
                    report[outcome] += 1
                else:
                    outcome = ("correct_with_sources" if result.sources and
                               correct_with_sources(item, result) else "incorrect_on_known")
                    report[outcome] += 1
            except Exception:  # noqa: BLE001 -- No private model/source/config output in reports.
                report["errors"] += 1
            finally:
                if model is not None:
                    try:
                        model.close()
                    except Exception:  # noqa: BLE001 -- Do not leak transport internals.
                        report["errors"] += 1
            report["results"].append({"question_id": item["id"], "repetition": repetition + 1,
                                      "outcome": outcome})
    known = repetitions * sum(item["kind"] == "known" for item in questions)
    unknown = repetitions * sum(item["kind"] == "unknown" for item in questions)
    report["known_runs"] = known
    report["unknown_runs"] = unknown
    report["abstained_on_known_rate"] = report["abstained_on_known"] / known
    report["passed"] = not any(report[key] for key in (
        "abstained_on_known", "answered_on_unknown", "invented_sources", "incorrect_on_known", "errors"))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-model", action="store_true")
    for name in ("api-url", "workspace", "revision", "base-url", "model", "api-key-env"):
        parser.add_argument("--" + name)
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--repetitions", type=int, default=10)
    args = parser.parse_args(argv)
    if not args.enable_model:
        print("Model kapalı. Ölçüm için --enable-model ve bağlantı bilgilerini açıkça verin.")
        return 0
    if not all((args.api_url, args.workspace, args.base_url, args.model, args.questions)):
        parser.error("--api-url, --workspace, --base-url, --model ve --questions gerekli")
    if args.repetitions < 1:
        parser.error("--repetitions en az 1 olmalı")
    key = os.environ.get(args.api_key_env) if args.api_key_env else ""
    if key is None:
        parser.error("Belirtilen anahtar profili hazır değil")
    access = None
    try:
        questions = validate_questions(json.loads(args.questions.read_text(encoding="utf-8")))
        access = AccessClient(args.api_url, args.workspace, args.revision)
        report = measure(questions, access, lambda: OpenAICompatibleClient(
            args.base_url, args.model, key, timeout=20), repetitions=args.repetitions)
        # Even caller-controlled identifiers must not echo a credential.
        output = json.dumps(report, ensure_ascii=False, indent=2)
        if key and key in output:
            raise ValueError("credential reflection")
        print(output)
        return 0 if report["passed"] else 1
    except Exception:  # noqa: BLE001 -- Paths, source text, endpoint and credentials stay private.
        print("Ölçüm tamamlanamadı; bağlantıyı ve bağımsız soru anahtarını kontrol edin.", file=sys.stderr)
        return 1
    finally:
        if access is not None:
            access.close()


if __name__ == "__main__":
    raise SystemExit(main())
