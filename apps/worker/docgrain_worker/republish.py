"""WP111: re-run merge + publish of a finished record job with the current review rules.

    python -m docgrain_worker.republish --workspace <workspace_id> [--job <job_id>] [--dry-run]

No extraction and no model call. The job's private runtime directory (``records/`` with each
document's ``source.json``, ``context.md`` and verified ``records.json``) is matched and merged
again on an output copy, refreshing structure pins only from the same canonical revision.
``apply_review_rules`` runs (karar 20), and the result is published as a new revision
under the same workspace publication lock and fences as the pipeline: no running record job,
publication head unchanged, demo mode off. It refuses when a person has already answered on the
head, because a re-merge would drop those answers. Without ``--job`` the job of the newest
published job revision is used. Prints the counts before and after as JSON.
"""

import argparse
import json
import os
import shutil
import sys
from hashlib import sha256
from urllib.parse import quote

import httpx
from docgrain_api import records_jobs as lifecycle
from docgrain_api import records_jobs_repository as jobs
from docgrain_api.settings import get_settings
from docgrain_records.api import SourceMetadata
from docgrain_records.auto_accept import (
    RULES_VERSION,
    apply_review_rules,
    human_accepted,
)
from docgrain_records.export import load_revision
from docgrain_records.match import (
    accept_strong_matches,
    load_records,
    propose_matches,
)
from docgrain_records.match_merge import merge_matches, write_json
from docgrain_records.review import questions, summary
from docgrain_records.runtime import revision_runtime
from docgrain_records.structure_context import (
    StructureIndex,
    identity_context,
    pin_structure,
    without_structure,
)

from .records_pipeline import review_counts


class RepublishError(RuntimeError):
    pass


def counts(revision):
    """Question and approval counts of one revision (the same numbers the summary API serves)."""
    report = summary(revision, revision.updated_at or "")
    slots = accepted = 0
    for record in revision.records:
        for merged in record.fields.values():
            for lang in {c.lang for c in merged.candidates if c.review_state != "rejected"}:
                slots += 1
                accepted += merged.accepted(lang) is not None
    return {"revision_id": revision.id, "records": report["records"],
            "accepted_records": sum(c["accepted_records"] for c in report["collections"]),
            "field_values": slots, "accepted_field_values": accepted,
            "accepted_ratio": round(report["accepted_ratio"], 4),
            "questions": len(questions(revision)), "conflicts": report["conflicts"],
            "duplicates": report["duplicates"], "needs_review": report["needs_review"],
            "unsupported_fields": report["unsupported_fields"]}


def _answered(revision):
    return bool(human_accepted(revision) or revision.history
                or any(d.same for d in revision.duplicate_decisions))


def _job_publication(store, workspace, job_id=None):
    for revision_id in store.list_revisions(workspace):
        found = store.manifest(workspace, revision_id).get("record_job_id")
        if found and (job_id is None or found == job_id):
            return found, revision_id
    raise RepublishError("no published revision of this record job in the workspace")


def _load_structure_snapshot(api, source):
    """Read only the canonical snapshot of the stored pin, never a newer document revision."""
    try:
        response = api.get(f"/v1/documents/{quote(source.document_id, safe='')}/knowledge")
        response.raise_for_status()
        snapshot = response.json().get("snapshot") or {}
        if ((snapshot.get("knowledge_revision") or {}).get("id") != source.knowledge_revision_id
                or snapshot.get("document_id") != source.document_id
                or snapshot.get("workspace_id") != source.workspace_id
                or (snapshot.get("source_version") or {}).get("id") != source.source_version_id
                or snapshot.get("root_node_id") not in {n["id"] for n in snapshot.get("structure", [])}):
            return None
        return snapshot
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None  # Missing/unavailable snapshots retain the job's original pins.


def _refresh_structure_pins(directory, out, results, workspace):
    """WP123: stage a matching copy; the extraction runtime and its evidence stay immutable."""
    paths = {json.loads(path.read_text(encoding="utf-8"))["document_id"]: path.parent
             for path in directory.rglob("records.json")}
    refreshed = 0
    api_url = os.environ.get("DOCGRAIN_INTERNAL_API_URL", "http://api:8000")
    with httpx.Client(base_url=api_url.rstrip("/"), timeout=60) as api:
        for result in results:
            original = paths[result.document_id]
            source = SourceMetadata.model_validate_json((original / "source.json").read_bytes())
            if source.document_id != result.document_id or source.workspace_id != workspace:
                raise RepublishError("record source pin belongs to another document or workspace")
            target = out / original.relative_to(directory)
            target.mkdir(parents=True, exist_ok=True)
            context = (original / "context.md").read_text(encoding="utf-8")
            snapshot = _load_structure_snapshot(api, source)
            if snapshot is not None:
                context = pin_structure(without_structure(context), snapshot)
                refreshed += 1
            structure = StructureIndex(context)
            for record in result.records:
                record.structure_context = identity_context(record, structure)
            shutil.copyfile(original / "source.json", target / "source.json")
            (target / "context.md").write_text(context, encoding="utf-8")
            write_json(target / "records.json", result.model_dump(mode="json"))
    return refreshed


def republish(workspace, job_id=None, *, dry_run=False):
    if get_settings().use_fixtures:
        raise RepublishError("demo mode: publications cannot change")
    store = lifecycle.pack_store()
    head_id = lifecycle.head(store, workspace)
    if head_id is None:
        raise RepublishError("workspace has no publication")
    head = store._source(workspace, head_id)
    if _answered(head):
        raise RepublishError("the newest publication has answers; re-merging would drop them")
    job_id, job_revision_id = _job_publication(store, workspace, job_id)
    base = head if head_id == job_revision_id else store._source(workspace, job_revision_id)
    root = store._path(workspace) / "runtime" / sha256(job_id.encode()).hexdigest()
    if not (root / "records").is_dir():
        raise RepublishError("record job runtime directory is missing")
    revision_id = f"u1_{job_id}_{RULES_VERSION}"
    report = {"workspace_id": workspace, "job_id": job_id, "revision_id": revision_id,
              "rules": RULES_VERSION, "before": counts(head)}
    if head_id == revision_id:
        return report | {"published": False, "note": "already published with these rules",
                         "after": report["before"]}
    runtime = revision_runtime(base)
    results = load_records(root / "records", runtime=runtime)
    out = root / "republish" / RULES_VERSION
    refreshed = _refresh_structure_pins(root / "records", out / "records", results, workspace)
    report["structure_pins_refreshed"] = f"{refreshed} of {len(results)} documents"
    matches = accept_strong_matches(results, propose_matches(results))
    # KULLANILMIYOR (karar 18, WP123): merge_matches(root / "records", results, matches, out, workspace, revision_id, "strong")
    merge_matches(out / "records", results, matches, out, workspace, revision_id, "strong")
    revision = load_revision((out / "merge_revision.json").read_bytes())
    if not revision.records:
        raise RepublishError("re-merge produced no records")
    revision, audit = apply_review_rules(revision)
    # Same lineage keeps question IDs stable; updated_at stays empty so a retry stages equal bytes.
    revision.parent_id = head.id
    revision.lineage_id = head.lineage_id or head.id
    report |= {"field_review_counts": review_counts(audit), "after": counts(revision)}
    if ([r.model_dump(mode="json") for r in revision.records], revision.decisions) == (
            [r.model_dump(mode="json") for r in head.records], head.decisions):
        return report | {"published": False, "note": "the newest publication already has these rules"}
    if dry_run:
        return report | {"published": False, "note": "dry run"}

    def check():
        """Pipeline fences, repeated inside the publication lock before the atomic rename."""
        if get_settings().use_fixtures:
            raise RepublishError("demo mode: publications cannot change")
        lifecycle.reap_locked(workspace)
        if jobs.active(workspace):
            raise RepublishError("a record job is running; try again when it has finished")
        if lifecycle.head(store, workspace) != head_id:
            raise RepublishError("publication changed meanwhile; run the command again")
        if _answered(store._source(workspace, head_id)):
            raise RepublishError("the newest publication has answers; re-merging would drop them")

    store.stage(revision)
    store.publish(revision, check=check)
    if lifecycle.head(store, workspace) != revision.id:
        raise RepublishError("new revision is not the publication head")
    return report | {"published": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--job", help="record job ID (default: newest published job revision)")
    parser.add_argument("--dry-run", action="store_true", help="compute and print, do not publish")
    args = parser.parse_args(argv)
    try:
        report = republish(args.workspace, args.job, dry_run=args.dry_run)
    except (RepublishError, lifecycle.JobConflict) as exc:
        print(f"republish stopped: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        # Validation messages can quote source values; print the type only.
        print(f"republish stopped: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
