"""Offline paired scoring and merge replay; private inputs/outputs stay local.

Use a frozen copy of the preceding record_golden.py as --before-scorer. Neither
extractors nor model clients are constructed. Existing match decisions are reused.
"""

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

from docgrain_eval import record_golden as after
from docgrain_eval.golden import load_jsonl
from docgrain_eval.scoring import normalized_value
from docgrain_records.match import MatchResult, load_records
from docgrain_records.match_merge import merge_matches, write_json
from docgrain_records.measurement import (
    extraction_scoring_records,
    merged_alignment_records,
    merged_scoring_views,
)
from docgrain_records.merge_models import MergeState


def load_before(path):
    spec = importlib.util.spec_from_file_location("docgrain_eval._before_record_golden", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def score(module, manifest, fields, views, contexts, proxies=None):
    mapping, ambiguities = module.align_records(fields, proxies or views)
    renamed = [dict(view, id=mapping.get(view["id"], view["id"])) for view in views]
    result = module.score_records(manifest, fields, renamed, contexts)
    result["source_identity_alignment"] = mapping
    result["source_identity_ambiguities"] = ambiguities
    return result


def conflicts(revision):
    total = trivial = 0
    per_collection = Counter()
    for record in revision.records:
        for name, field in record.fields.items():
            for choices in field.conflicts.values():
                total += 1
                per_collection[record.type] += 1
                keys = {json.dumps(normalized_value(c.value, name), sort_keys=True) for c in choices}
                trivial += len(keys) == 1
    return {"language_field_conflicts": total, "trivial_conflicts": trivial,
            "per_collection": dict(sorted(per_collection.items()))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before-scorer", "golden-dir", "records-dir", "merged-dir", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise ValueError("output already exists; preserve previous measurement")
    args.out.mkdir(parents=True)
    before = load_before(args.before_scorer)
    manifest_path = args.golden_dir / "manifest.frozen.v2.json"
    fields_path = args.golden_dir / "fields.jsonl"
    questions_path = args.golden_dir / "questions.jsonl"
    manifest = after.Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    after.check_sources(manifest, args.golden_dir)
    fields = load_jsonl(fields_path, after.GoldenField)
    coverage = after.validate_key(manifest, fields, load_jsonl(questions_path, after.GoldenQuestion))
    input_paths = [args.before_scorer, manifest_path, fields_path, questions_path,
                   args.merged_dir / "merge_state.json", args.merged_dir / "merge_revision.json",
                   args.merged_dir / "match_proposals.json",
                   *sorted(args.records_dir.rglob("records.json")),
                   *sorted(args.records_dir.rglob("source.json")),
                   *sorted(args.records_dir.rglob("context.md"))]
    receipts = {str(p.resolve()): after.digest(p) for p in input_paths}
    results = load_records(args.records_dir)
    languages = {r.document_id: r.lang for r in results}
    contexts = {}
    for path in args.records_dir.rglob("records.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))["document_id"]
        contexts[doc] = path.with_name("context.md").read_text(encoding="utf-8")
    original = MergeState.model_validate_json((args.merged_dir / "merge_state.json").read_text(encoding="utf-8"))
    revision_id = json.loads((args.merged_dir / "merge_revision.json").read_text(encoding="utf-8"))["id"]
    revision = original.revisions[revision_id]
    matches = MatchResult.model_validate_json((args.merged_dir / "match_proposals.json").read_text(encoding="utf-8"))
    replay = merge_matches(args.records_dir, results, matches, args.out / "merged",
                           revision_id="taxonomy-replay-v1")
    replay_state = MergeState.model_validate_json((args.out / "merged/merge_state.json").read_text(encoding="utf-8"))
    measurements = {}
    extraction = [view for r in results for view in extraction_scoring_records(r)]
    for label, views, proxies in [("extracted", extraction, None), *[
        (label, views, merged_alignment_records(views, results, original.identity_map))
        for label, views in (
            ("merged_primary", merged_scoring_views(revision, languages)),
            ("merged_source_language", merged_scoring_views(revision, languages, source_language=True)),
        )
    ]]:
        for version, module in (("before", before), ("after", after)):
            report = score(module, manifest, fields, views, contexts, proxies)
            report["coverage"] = coverage
            report["d4_target"]["criteria_met"] = coverage["ready"] and report["d4_target"]["measurement_met"]
            write_json(args.out / f"{label}_{version}.json", report)
            measurements[f"{label}_{version}"] = {k: report[k] for k in ("overall", "per_collection", "d4_target")}
    for label, views in (
        ("replayed_primary", merged_scoring_views(replay, languages)),
        ("replayed_source_language", merged_scoring_views(replay, languages, source_language=True)),
    ):
        proxies = merged_alignment_records(views, results, replay_state.identity_map)
        report = score(after, manifest, fields, views, contexts, proxies)
        write_json(args.out / f"{label}.json", report)
        measurements[label] = {k: report[k] for k in ("overall", "per_collection", "d4_target")}
    unchanged = all(after.digest(p) == receipts[str(p.resolve())] for p in input_paths)
    summary = {"measurements": measurements, "conflicts_before": conflicts(revision),
               "conflicts_after": conflicts(replay), "input_receipts": receipts,
               "inputs_unchanged": unchanged, "model_calls": 0}
    write_json(args.out / "summary.json", summary)
    for label, result in measurements.items():
        metric = result["overall"]
        print(f"{label}: {metric['correct_fields']}/{metric['expected_fields']}")
    print(json.dumps({k: summary[k] for k in ("conflicts_before", "conflicts_after", "inputs_unchanged", "model_calls")}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, TypeError) as exc:
        print(f"Offline replay failed ({type(exc).__name__}); check local inputs.", file=sys.stderr)
        sys.exit(1)
