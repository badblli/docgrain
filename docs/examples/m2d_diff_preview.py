"""Read-only counterfactual diff preview: never persists edits or calls a provider."""

import argparse
import json
from pathlib import Path

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot, processing_revision_id
from docgrain_domain.canonical.chunking import ChunkingSpec
from docgrain_domain.canonical.incremental import canonical_diff, plan_chunks
from docgrain_domain.canonical.lifecycle import ProcessingSpec, scoped_id


def preview(snapshot, scenario, mutate):
    value = snapshot.model_dump(mode="json")
    mutate(value)
    revision = value["knowledge_revision"]
    revision["parent_revision_id"] = snapshot.knowledge_revision.id
    if snapshot.knowledge_revision.processing:
        revision["processing"]["mapper_version"] += ":counterfactual:" + scenario
        processing = ProcessingSpec.model_validate(revision["processing"])
        revision["id"] = processing_revision_id(snapshot.source_version.id, processing)
        for producer in revision["producers"]:
            producer["configuration_digest"] = processing.digest
    else:
        revision["id"] = scoped_id("counterfactual", [snapshot.knowledge_revision.id, scenario])
    changed = CanonicalKnowledgeSnapshot.model_validate(value)
    spec = ChunkingSpec(max_table_rows=1)
    plan = plan_chunks(snapshot, changed, spec)
    return {"scenario": scenario, "simulated": True, "document_id": snapshot.document_id,
            "source_unchanged": True, "counts": {key: len(items) for key, items in plan.model_dump().items()},
            "diff": canonical_diff(snapshot, changed).model_dump(mode="json"), "plan": plan.model_dump(mode="json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    snapshot = CanonicalKnowledgeSnapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
    table = max((n for n in snapshot.structure if n.kind == "table"), key=lambda n: len(n.rows), default=None)
    scenarios = [preview(snapshot, "provenance-only", lambda v: v["evidence"][0].update(note="Counterfactual evidence correction"))]
    if table and table.rows:
        def cell(value):
            target = next(n for n in value["structure"] if n["id"] == table.id)["rows"][0][-1]
            target["value"] = str(target["value"]) + " [simulated edit]"
            target["display_text"] = str(target["value"])
        def row(value):
            next(n for n in value["structure"] if n["id"] == table.id)["rows"].pop()
        scenarios += [preview(snapshot, "single-cell-edit", cell), preview(snapshot, "last-row-removal", row)]
    args.output.write_text(json.dumps(scenarios, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([{k: v for k, v in item.items() if k not in {"diff", "plan"}} for item in scenarios], ensure_ascii=False))


if __name__ == "__main__":
    main()
