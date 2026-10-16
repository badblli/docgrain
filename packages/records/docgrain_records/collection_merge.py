"""WP119: "Bu iki liste aynı şeyi mi anlatıyor?" — unsure structure groupings asked once.

The structure stage (``structure_records``) groups Docling tables and lists into collections. A
grouping it is not sure about (``weak_overlap``, ``would_bridge_collections``) is stored on the
revision as a ``CollectionMergeQuestion``. The answer is a ``CollectionMergeDecision`` keyed by
stable unit-pair signatures: "same" joins the two lists in the published revision right away and
in every later run; "different" keeps them apart and is never asked again.
"""

from copy import deepcopy
from hashlib import sha256

from .duplicates import answer_duplicate, normalized_name
from .export import encode
from .merge_models import CollectionMergeDecision, MergeRevision
from .runtime import revision_runtime

QUESTION_TR = "Bu iki liste aynı şeyi mi anlatıyor?"


def remembered(revisions) -> dict[str, bool]:
    """Signature -> same, from the answers kept on earlier revisions (later answers win)."""
    decisions: dict[str, bool] = {}
    for revision in revisions:
        for decision in revision.collection_merge_decisions:
            for signature in decision.signatures:
                decisions[signature] = decision.same
    return decisions


def _decided(revision: MergeRevision) -> set[str]:
    return {s for d in revision.collection_merge_decisions for s in d.signatures}


def collection_merge_questions(revision, runtime, definitions, label, documents) -> list[dict]:
    decided = _decided(revision)
    present = set(runtime.collections.values())
    result = []
    for question in revision.collection_merges:
        sides = (question.left, question.right)
        if decided & set(question.signatures) or any(s.collection not in present for s in sides):
            continue
        cards = []
        for side in sides:
            fields = [{"key": "records", "label": "Örnek kayıtlar", "value": ", ".join(side.records)},
                      {"key": "record_count", "label": "Kayıt sayısı", "value": side.record_count}]
            cards.append({"id": side.collection, "title": side.label, "fields": fields,
                          "sources": [{"document_id": document, "document_name":
                                       documents.get(document, document), "locator": None,
                                       "quote": None} for document in side.documents]})
        identity = [revision.workspace_id, revision.lineage_id or revision.id, "collection_merge",
                    sorted(question.signatures)]
        left = question.left.collection
        result.append({
            "id": "q_" + sha256(encode(identity)).hexdigest(), "kind": "collection_merge",
            "collection": left, "collection_label": label(definitions.get(left, {}), left),
            "record_id": left, "record_ids": [],
            "record_title": f"{question.left.label} / {question.right.label}",
            "field": "", "field_label": "Aynı liste mi?", "lang": None, "options": [],
            "question_tr": QUESTION_TR, "duplicate_records": cards,
            "collections": [question.left.collection, question.right.collection],
            "signatures": sorted(question.signatures), "reason": question.reason})
    return result


def answer_collection_merge(revision: MergeRevision, question: dict, same: bool) -> None:
    """Record the answer; "same" moves the right list's records and fields into the left list."""
    keep, retired = question["collections"]
    revision.collection_merge_decisions.append(CollectionMergeDecision(
        question_id=question["id"], signatures=question["signatures"],
        collections=[keep, retired], same=same, at=revision.updated_at))
    if not same:
        return
    schema = deepcopy(revision.workspace_schema)
    collections = {c["key"]: c for c in schema["collections"]}
    target, source = collections[keep], collections[retired]
    known = {f["key"]: f for f in target["fields"]}
    for definition in source["fields"]:
        existing = known.get(definition["key"])
        if existing is None:
            target["fields"].append(definition)
            known[definition["key"]] = definition
        elif (existing["type"], existing.get("unit")) != (definition["type"], definition.get("unit")):
            raise ValueError("lists define the same field differently")
    target["examples"] = target["examples"] + source["examples"]
    target["aliases"] = sorted(set(target.get("aliases", [])) | set(source.get("aliases", []))
                               | {retired})
    schema["collections"] = [c for c in schema["collections"] if c["key"] != retired]
    revision.workspace_schema = schema
    for record in revision.records:
        if record.type == retired:
            record.type = keep
    runtime = revision_runtime(revision)
    identity = runtime.identities[keep]
    # Items with the same name in both lists are one record (decision 21); values that differ
    # stay as candidates and become questions as usual.
    seen: dict[str, str] = {}
    for record in sorted((r for r in revision.records if r.type == keep), key=lambda r: r.id):
        field = record.fields.get(identity)
        names = sorted({normalized_name(c.value) for c in field.candidates
                        if c.review_state != "rejected"} - {""}) if field else []
        if not names:
            continue
        other = next((seen[name] for name in names if name in seen), None)
        if other is None:
            for name in names:
                seen[name] = record.id
            continue
        answer_duplicate(revision, {"id": question["id"], "record_ids": [other, record.id]},
                         True, runtime)
