"""Translate reviewed pair suggestions into wp42 aliases, preserving source checks."""

import json
from pathlib import Path

from pydantic import ValidationError

from .api import SourceMetadata
from .match import (
    accept_strong_matches,
    candidate_groups,
    fingerprint,
    identity_conflict,
    record_ref,
    ref_key,
    source_identity,
    summarize_matches,
)
from .merge import JsonMergeStore, _source_key
from .merge_models import AliasDecision
from .runtime import HOSPITALITY, RuntimeRecords


def load_merge_documents(directory, results, workspace_id=None, *, runtime=None):
    """Require actual pinned source context, never synthesize it from quotations."""
    paths = {}
    for path in Path(directory).rglob("records.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        paths[raw["document_id"]] = path.parent
    documents = []
    runtime = runtime or runtime_for_results(results)
    for result in results:
        root = paths[result.document_id]
        if not (root / "source.json").exists() or not (root / "context.md").exists():
            raise ValueError("merge requires source.json pins and the corresponding context.md beside each records.json")
        try:
            metadata = SourceMetadata.model_validate_json((root / "source.json").read_text(encoding="utf-8"))
            if metadata.document_id != result.document_id or metadata.lang != result.lang:
                raise ValueError("merge source pin does not match extraction document and language")
            if workspace_id is not None and metadata.workspace_id != workspace_id:
                raise ValueError("merge source pin belongs to another workspace")
            documents.append(runtime.merge_document({
                "workspace_id": metadata.workspace_id, "document_id": result.document_id,
                "source_version_id": metadata.source_version_id,
                "knowledge_revision_id": metadata.knowledge_revision_id,
                "content_sha256": metadata.content_sha256,
                "document_name": metadata.filename,
                "context": (root / "context.md").read_text(encoding="utf-8"),
                "records": [{"source_identity": source_identity(record), "record": record.model_dump(mode="json")}
                         for record in result.records],
            }))
        except ValidationError as exc:
            raise ValueError("merge source has invalid pins or duplicate type/name identities") from exc
    if len({document.workspace_id for document in documents}) != 1:
        raise ValueError("merge documents belong to different workspaces")
    return documents


def runtime_for_results(results):
    schemas = [getattr(result, "workspace_schema", None) for result in results]
    if not schemas or any(schema != schemas[0] for schema in schemas):
        raise ValueError("merge requires one accepted workspace schema version")
    return RuntimeRecords(schemas[0]) if schemas[0] else HOSPITALITY


def apply_matches(documents, matches):
    """Apply only explicit accepted/same reviews. Digests reject stale proposals."""
    documents = [d.model_copy(deep=True) for d in documents]
    entries = {ref_key(record_ref(d.document_id, item.record)): (d, item)
               for d in documents for item in d.records}
    seen = set()
    for proposal in matches.proposals:
        if proposal.id in seen:
            raise ValueError("duplicate match proposal")
        seen.add(proposal.id)
        for ref in (proposal.left, proposal.right):
            if ref_key(ref) not in entries:
                raise ValueError("match proposal is stale or targets a different records input")
    groups = candidate_groups(matches.proposals, accepted_only=True)
    for group in groups:
        docs = [key[0] for key in group]
        if len(docs) != len(set(docs)):
            raise ValueError("accepted aliases would merge distinct records from one document")
        if any((p.decision == "different" or p.review_state == "rejected")
               and ref_key(p.left) in group and ref_key(p.right) in group
               for p in matches.proposals):
            raise ValueError("accepted aliases would bypass a conflicting pair")
        ordered = sorted(group)
        if any(identity_conflict(entries[a][1].record, entries[b][1].record, strong_names=True)
               for i, a in enumerate(ordered) for b in ordered[i + 1:]):
            raise ValueError("accepted aliases would bypass a conflicting pair")
        alias = "reviewed-match:" + fingerprint(sorted(group))
        for key in group:
            entries[key][1].aliases.append(alias)
    for p in matches.proposals:
        if p.review_state != "accepted":
            a, b = entries[ref_key(p.left)], entries[ref_key(p.right)]
            a[1].match_exclusions.append(_source_key(*b))
            b[1].match_exclusions.append(_source_key(*a))
    return documents, groups, entries


def merge_matches(directory, results, matches, out, workspace_id=None, revision_id=None,
                  auto_accept=None):
    if auto_accept not in {None, "strong"}:
        raise ValueError("unknown automatic acceptance rule")
    if auto_accept == "strong":
        matches = accept_strong_matches(results, matches)
    runtime = runtime_for_results(results)
    documents = load_merge_documents(directory, results, workspace_id, runtime=runtime)
    documents, groups, entries = apply_matches(documents, matches)
    out = Path(out)
    store = JsonMergeStore(out / "merge_state.json", documents[0].workspace_id)
    state = store._read()
    decisions = []
    for group in groups:
        known = set()
        for key in group:
            document, item = entries[key]
            known.update(state.identity_map.get(_source_key(document, item), []))
        if len(known) > 1:
            reviews = sorted([p for p in matches.proposals if p.review_state == "accepted"
                              and ref_key(p.left) in group], key=lambda p: p.id)
            keeper = min(known)
            for old in sorted(known - {keeper}):
                decisions.append(AliasDecision(
                    keep_id=keeper, retired_id=old, proposal_ids=[p.id for p in reviews],
                    reviewer="; ".join(sorted({p.reviewer for p in reviews})),
                    reason="; ".join(p.reason for p in reviews),
                ))
    revision_id = revision_id or "merge_" + fingerprint([
        [d.model_dump(mode="json") for d in documents], matches.model_dump(mode="json"),
    ])
    # Preserve the same explicit ID consolidation when repeating a saved request.
    if revision_id in state.revisions:
        decisions = state.revisions[revision_id].alias_decisions
    revision = store.merge(revision_id, documents, alias_decisions=decisions, runtime=runtime)
    write_json(out / "merge_revision.json", revision.model_dump(mode="json"))
    write_json(out / "match_proposals.json", matches.model_dump(mode="json"))
    summary = summarize_matches(results, matches)
    for kind, counts in summary["counts"].items():
        counts["merged_records"] = sum(r.type == kind for r in revision.records)
    write_json(out / "merge_summary.json", summary)
    write_json(out / "aliases.json", {
        "accepted_proposals": [p.model_dump(mode="json") for p in matches.proposals
                               if p.review_state == "accepted"],
        "aliases": [{"document_id": d.document_id, "source_identity": item.source_identity,
                     "type": item.record.type, "aliases": item.aliases}
                    for d in documents for item in d.records if item.aliases],
        "id_decisions": [d.model_dump(mode="json") for d in decisions],
    })
    for kind in runtime.models:
        write_json(out / f"{kind}.json", [r.model_dump(mode="json") for r in revision.records if r.type == kind])
    return revision


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
