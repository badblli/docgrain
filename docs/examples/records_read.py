"""Publish a neutral synthetic pack and measure stored direct-context preparation.

Run with the repository venv: python docs/examples/records_read.py --root storage/records
This intentionally performs no model, HTTP, extraction or source-document calls.
"""

import argparse
import json
import platform
import statistics
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/api"), str(ROOT / "packages/records"),
               str(ROOT / "packages/domain")]

from docgrain_api.records_repository import RecordsRepository
from docgrain_records.export import load_revision
from docgrain_records.merge_models import MergeRevision


def synthetic_revision(count=200):
    records = []
    for i in range(count):
        fields = {}
        for name, value, lang in (("name", f"Garden room {i}", "en"),
                                  ("capacity", 2, "en"), ("view", "Garden", "en")):
            fields[name] = {"primary_lang": lang, "candidates": [{
                "id": f"fact-{i}-{name}", "value": value, "lang": lang,
                "review_state": "accepted", "evidence": [{
                    "document_id": "doc-synthetic", "source_version_id": "s1",
                    "knowledge_revision_id": "k1", "locator": f"paragraph-{i}",
                    "quote": str(value),
                }],
            }]}
        records.append({"id": f"rec-{i}", "type": "room_type", "fields": fields})
    return MergeRevision.model_validate({
        "workspace_id": "workspace-synthetic", "id": "synthetic-rooms-200-v1",
        "documents": [{"document_id": "doc-synthetic", "source_version_id": "s1",
                       "knowledge_revision_id": "k1"}], "records": records,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--revision-file", type=Path,
                        help="Optional offline wp42 MergeRevision JSON; never prints contents")
    args = parser.parse_args()
    revision = (load_revision(args.revision_file.read_bytes())
                if args.revision_file else synthetic_revision())
    store = RecordsRepository(args.root)
    store.publish(revision)
    if args.revision_file:
        counts = {}
        for mode in ("preview", "approved"):
            if revision.workspace_schema:
                counts[mode] = {collection: len(json.loads(store.read(
                    revision.workspace_id, revision.id, collection, mode=mode)))
                    for collection in store.manifest(revision.workspace_id, revision.id)["collections"]}
            else:
                rows = json.loads(store.read(revision.workspace_id, revision.id, "rooms", mode=mode))
                counts[mode] = {"rooms": len(rows),
                                "rooms_with_name": sum("name" in row for row in rows),
                                "rooms_with_capacity": sum("capacity" in row for row in rows)}
        print(json.dumps(counts, indent=2))
        return
    def prepare():
        return store.read(revision.workspace_id, revision.id, "rooms", compact=True,
                          mode="preview").decode("utf-8")
    for _ in range(20):
        prepare()
    durations = []
    for _ in range(200):
        started = perf_counter()
        body = prepare()
        durations.append((perf_counter() - started) * 1000)
    print(json.dumps({"fixture": revision.id, "records": len(revision.records),
                      "warmup": 20, "reads": len(durations), "context_chars": len(body),
                      "p95_ms": sorted(durations)[189],
                      "median_ms": statistics.median(durations),
                      "platform": platform.platform(), "processor": platform.processor(),
                      "python": platform.python_version()}, indent=2))


if __name__ == "__main__":
    main()
