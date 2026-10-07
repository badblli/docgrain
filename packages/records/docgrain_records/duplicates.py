"""Offline duplicate suggestions; only a person's answer can consolidate records."""

import re
from difflib import SequenceMatcher
from hashlib import sha256
from itertools import combinations

from docgrain_eval.scoring import normalized_value

from .export import encode
from .merge_models import DuplicateDecision
from .multivalue import multiple_values

_TURKISH = str.maketrans("çğıöşü", "cgiosu")
_STOP = {"oda", "odasi", "odalar", "room", "rooms", "suite", "suites", "suit", "suits"}


def normalized_name(value):
    if not isinstance(value, str):
        return ""
    tokens = re.findall(r"[a-z0-9]+", value.casefold().translate(_TURKISH).replace("\u0307", ""))
    return " ".join(sorted(token for token in tokens if token not in _STOP))


def _values(field, key):
    return {encode(normalized_value(c.value, key)) for c in field.candidates
            if c.review_state != "rejected"}


def duplicate_pairs(revision, runtime):
    """Require a distinctive name AND corroborating fields, never name similarity alone."""
    dismissed = {tuple(sorted(d.record_ids)) for d in revision.duplicate_decisions if not d.same}
    groups = {}
    for record in revision.records:
        groups.setdefault(record.type, []).append(record)
    result = []
    for kind, records in sorted(groups.items()):
        identity = runtime.identities[kind]
        for left, right in combinations(sorted(records, key=lambda r: r.id), 2):
            if (left.id, right.id) in dismissed:
                continue
            names = []
            for record in (left, right):
                field = record.fields.get(identity)
                names.append({normalized_name(c.value) for c in field.candidates
                              if c.review_state != "rejected" and normalized_name(c.value)}
                             if field else set())
            similarity = max((SequenceMatcher(None, a, b).ratio()
                              for a in names[0] for b in names[1]), default=0)
            if similarity < 0.92:
                continue
            shared = different = 0
            for key in sorted((left.fields.keys() & right.fields.keys()) - {identity}):
                a, b = _values(left.fields[key], key), _values(right.fields[key], key)
                if a and b:
                    shared += len(a) == len(b) == 1 and a == b
                    different += a.isdisjoint(b)
            score = round(0.85 * similarity + 0.05 * min(shared, 2) - 0.05 * different, 3)
            if shared and (similarity == 1 or shared >= 2) and score >= 0.85:
                result.append((left, right, score))
    return result


def duplicate_questions(revision, runtime, rows, definitions, documents, label, locator):
    by_id = {row["id"]: row for collection in rows.values() for row in collection}
    result = []
    for left, right, score in duplicate_pairs(revision, runtime):
        collection = runtime.collections[left.type]
        definition = definitions.get(collection, {})
        fields = {f["key"]: f for f in definition.get("fields", [])}
        identity = runtime.identities[left.type]
        cards = []
        for record in (left, right):
            row = by_id.get(record.id, {})
            keys = sorted(record.fields.keys() - {identity})
            # Prefer compact comparable facts before descriptions and long lists.
            keys.sort(key=lambda key: (isinstance(row.get(key), (list, dict)),
                                       len(str(row.get(key, ""))), key))
            sources = []
            for evidence in row.get("_meta", {}).get("sources", []):
                sources.append({"document_id": evidence.get("document_id"),
                                "document_name": documents.get(evidence.get("document_id"),
                                                               "Sizin düzeltmeniz"),
                                "locator": locator(evidence["locator"]) if "locator" in evidence
                                else None, "quote": evidence.get("quote")})
            cards.append({"id": record.id, "title": row.get(identity, record.id),
                          "fields": [{"key": key, "label": label(fields.get(key, {}), key),
                                      "value": row[key]} for key in keys if key in row][:4],
                          "sources": sources})
        record_ids = [left.id, right.id]
        question_id = "q_" + sha256(encode([
            revision.workspace_id, revision.lineage_id or revision.id, "duplicate", record_ids,
        ])).hexdigest()
        result.append({"id": question_id, "kind": "duplicate", "collection": collection,
                       "collection_label": label(definition, collection),
                       "record_id": left.id, "record_ids": record_ids,
                       "record_title": " / ".join(str(card["title"]) for card in cards),
                       "field": identity, "field_label": "Aynı kayıt mı?", "lang": None,
                       "options": [], "question_tr": "Bu iki kayıt aynı mı?",
                       "duplicate_records": cards, "score": score})
    return result


def answer_duplicate(revision, question, same, runtime):
    keep_id, retired_id = question["record_ids"]
    revision.duplicate_decisions.append(DuplicateDecision(
        question_id=question["id"], record_ids=[keep_id, retired_id], same=same,
        at=revision.updated_at))
    if not same:
        return
    keep, retired = (next(r for r in revision.records if r.id == key)
                     for key in (keep_id, retired_id))
    for key, incoming in retired.fields.items():
        if key not in keep.fields:
            keep.fields[key] = incoming.model_copy(deep=True)
            continue
        field = keep.fields[key]
        buckets = {}
        for candidate in sorted(field.candidates + incoming.candidates, key=lambda c: c.id):
            signature = encode([candidate.lang, normalized_value(candidate.value, key)])
            if signature not in buckets:
                buckets[signature] = candidate.model_copy(deep=True)
                continue
            existing = buckets[signature]
            citations = {encode(e.model_dump(mode="json")): e
                         for e in existing.evidence + candidate.evidence}
            existing.evidence = [citations[k] for k in sorted(citations)]
            states = {existing.review_state, candidate.review_state}
            existing.review_state = next(state for state in (
                "accepted", "needs_review", "proposed", "rejected") if state in states)
        field.candidates = list(buckets.values())
        field.multi_value_languages = sorted(set(field.multi_value_languages)
                                            | set(incoming.multi_value_languages))
        for lang in {c.lang for c in field.candidates}:
            active = [c for c in field.candidates if c.lang == lang and c.review_state != "rejected"]
            # A previous approval in either separate record cannot settle a new conflict.
            if len(active) > 1 and not multiple_values(runtime, keep, key, field, lang, active):
                for candidate in active:
                    candidate.review_state = "needs_review"
    revision.records = [r for r in revision.records if r.id != retired_id]
    # A prior "different" answer remains a veto after a third record is consolidated.
    for decision in revision.duplicate_decisions:
        if not decision.same:
            decision.record_ids = sorted({keep_id if key == retired_id else key
                                          for key in decision.record_ids})
