"""Offline questions and immutable, evidenced answers for published records."""

import re
from collections import defaultdict
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from pydantic import JsonValue, model_validator

from .auto_accept import auto_slots, rule_decisions
from .duplicates import answer_duplicate, duplicate_questions
from .export import encode, project_records
from .merge_models import AnswerHistory, FactCandidate, MergeRevision, UserEditEvidence
from .models import StrictModel, Text
from .multivalue import list_field, multiple_values
from .runtime import revision_runtime
from .schedule import document_dates, same_recurrence
from .schedule_review import combine_swaps, schedule_question


class CandidateAnswer(StrictModel):
    candidate_id: Text


class DocumentAnswer(StrictModel):
    document_id: Text


class DuplicateAnswer(StrictModel):
    same: bool


class EditAnswer(StrictModel):
    value: JsonValue
    note: str


class AllAnswer(StrictModel):
    all: bool

    @model_validator(mode="after")
    def true_only(self):
        if not self.all:
            raise ValueError("all must be true")
        return self


class SkipAnswer(StrictModel):
    skip: bool

    @model_validator(mode="after")
    def true_only(self):
        if not self.skip:
            raise ValueError("skip must be true")
        return self


Answer = CandidateAnswer | DocumentAnswer | EditAnswer | SkipAnswer | AllAnswer | DuplicateAnswer


def _label(definition, key):
    return next((label["value"] for label in definition.get("label_i18n", [])
                 if label["lang"] == "tr"), key)


def _display(value):
    return value if isinstance(value, str) else encode(value).decode()


def _locator(value):
    page = re.search(r"\b(?:p\.|page|s\.)\s*(\d+)\b", value, re.IGNORECASE)
    if page:
        return "s. " + page.group(1)
    section = re.search(r"§\s*(\d+)", value)
    return "§ " + section.group(1) if section else value


def questions(revision: MergeRevision) -> list[dict]:
    """Unresolved field slots, schedules and conservative record-pair questions."""
    runtime = revision_runtime(revision)
    definitions = {c["key"]: c for c in (runtime.schema or {}).get("collections", [])}
    rows = project_records(revision, "tr")
    titles = {row["id"]: _display(row.get(runtime.identities[kind], row["id"]))
              for kind, key in runtime.collections.items() for row in rows[key]}
    documents = {pin.document_id: pin.document_name or pin.document_id
                 for pin in revision.documents}
    result = []
    for record in sorted(revision.records, key=lambda r: r.id):
        collection = runtime.collections[record.type]
        definition = definitions.get(collection, {})
        fields = {f["key"]: f for f in definition.get("fields", [])}
        for field, merged in sorted(record.fields.items()):
            languages = defaultdict(list)
            for candidate in merged.candidates:
                if candidate.review_state != "rejected":
                    languages[candidate.lang].append(candidate)
            for lang, candidates in sorted(languages.items()):
                if any(c.review_state == "accepted" for c in candidates):
                    continue
                schedules = document_dates(field, candidates)
                if schedules and len(schedules) > 1 and same_recurrence(schedules):
                    continue
                if len(candidates) > 1 and multiple_values(
                        runtime, record, field, merged, lang, candidates):
                    continue
                kind = "conflict" if len(candidates) > 1 else "needs_review"
                if kind == "needs_review" and candidates[0].review_state != "needs_review":
                    continue
                identity = [revision.workspace_id, revision.lineage_id or revision.id,
                            record.id, field, lang]
                options = []
                for candidate in sorted(candidates, key=lambda c: c.id):
                    # A shared value can cite several documents/locations. Expose every
                    # citation so document groups never lose a quote or invent a source.
                    citations = sorted(candidate.evidence, key=lambda e: (
                        "", "", e.note) if isinstance(e, UserEditEvidence) else
                        (e.document_id, e.locator, e.quote))
                    for evidence in citations:
                        user_edit = isinstance(evidence, UserEditEvidence)
                        options.append({
                            "candidate_id": candidate.id, "value": candidate.value,
                            "display": _display(candidate.value),
                            "quote": None if user_edit else evidence.quote,
                            "document_id": None if user_edit else evidence.document_id,
                            "document_name": "Sizin düzeltmeniz" if user_edit else
                            documents[evidence.document_id],
                            "locator": None if user_edit else _locator(evidence.locator),
                        })
                question = {
                    "id": "q_" + sha256(encode(identity)).hexdigest(), "kind": kind,
                    "collection": collection, "collection_label": _label(definition, collection),
                    "record_id": record.id, "record_title": titles.get(record.id, record.id),
                    "field": field, "field_label": _label(fields.get(field, {}), field),
                    "lang": lang, "options": options,
                    "allow_all": len(candidates) > 1 and not list_field(runtime, record.type, field),
                }
                if schedules and len(schedules) > 1:
                    question = schedule_question(question, schedules, candidates, documents)
                result.append(question)
    result = combine_swaps(result, revision.workspace_id, revision.lineage_id or revision.id)
    result.extend(duplicate_questions(revision, runtime, rows, definitions, documents,
                                      _label, _locator))
    return sorted(result, key=lambda q: ({"duplicate": 1, "needs_review": 2}.get(q["kind"], 0),
                                        q["collection"], q["record_id"], q["field"], q["lang"] or ""))


def auto_accepted(revision: MergeRevision) -> list[dict]:
    """WP111: values a rule accepted (karar 20), shaped like questions so a person can change them.

    Not part of ``questions``/counts. The ID is the slot's question ID; answering it with a
    candidate (also a recorded variant), a document, all values or a correction replaces the
    rule's choice and records the answer in the history like any other answer.
    """
    runtime = revision_runtime(revision)
    definitions = {c["key"]: c for c in (runtime.schema or {}).get("collections", [])}
    rows = project_records(revision, "tr")
    titles = {row["id"]: _display(row.get(runtime.identities[kind], row["id"]))
              for kind, key in runtime.collections.items() for row in rows[key]}
    documents = {pin.document_id: pin.document_name or pin.document_id
                 for pin in revision.documents}
    rules = rule_decisions(revision)
    result = []
    for record, field, lang, candidates in auto_slots(revision):
        collection = runtime.collections[record.type]
        definition = definitions.get(collection, {})
        fields = {f["key"]: f for f in definition.get("fields", [])}
        identity = [revision.workspace_id, revision.lineage_id or revision.id, record.id, field, lang]
        options = []
        for candidate in sorted(candidates, key=lambda c: (c.review_state != "accepted", c.id)):
            decision = rules.get((record.id, field, candidate.id))
            for evidence in sorted(candidate.evidence, key=lambda e: (
                    e.document_id, e.locator, e.quote)):
                options.append({
                    "candidate_id": candidate.id, "value": candidate.value,
                    "display": _display(candidate.value), "quote": evidence.quote,
                    "document_id": evidence.document_id,
                    "document_name": documents[evidence.document_id],
                    "locator": _locator(evidence.locator),
                    "accepted": candidate.review_state == "accepted",
                    "reviewer": decision.reviewer if decision else None,
                })
        accepted = [c for c in candidates if c.review_state == "accepted"]
        result.append({
            "id": "q_" + sha256(encode(identity)).hexdigest(), "kind": "auto_accepted",
            "collection": collection, "collection_label": _label(definition, collection),
            "record_id": record.id, "record_title": titles.get(record.id, record.id),
            "field": field, "field_label": _label(fields.get(field, {}), field), "lang": lang,
            "reviewer": rules[(record.id, field, accepted[0].id)].reviewer,
            "options": options,
            # "All" only where the rule itself accepted several values (one document's list).
            "allow_all": len(accepted) > 1 and not list_field(runtime, record.type, field),
        })
    return result


def summary(revision: MergeRevision, updated_at: str) -> dict:
    """Count published preview fields; each language value is a field slot."""
    runtime = revision_runtime(revision)
    definitions = {c["key"]: c for c in (runtime.schema or {}).get("collections", [])}
    projected = project_records(revision)
    pending = questions(revision)
    records = {r.id: r for r in revision.records}
    accepted = total = unsupported = 0
    collections = []
    for key, rows in projected.items():
        for row in rows:
            for field, metadata in row["_meta"]["fields"].items():
                for lang, evidence in metadata["i18n"].items():
                    total += 1
                    accepted += records[row["id"]].fields[field].accepted(lang) is not None
                    unsupported += not any(
                        e.get("quote") or e.get("kind") == "user_edit" for e in evidence)
        pending_records = {record_id for q in pending if q["collection"] == key
                           for record_id in q.get("record_ids", [q["record_id"]])}
        approved_records = sum(
            row["id"] not in pending_records and bool(row["_meta"]["fields"]) and all(
                records[row["id"]].fields[field].accepted(lang) is not None
                for field, metadata in row["_meta"]["fields"].items()
                for lang in metadata["i18n"])
            for row in rows)
        collections.append({"key": key, "label": _label(definitions.get(key, {}), key),
                            "records": len(rows),
                            "accepted_records": approved_records,
                            "pending_records": len(pending_records),
                            "duplicates": sum(q["collection"] == key and q["kind"] == "duplicate"
                                              for q in pending),
                            "conflicts": sum(q["collection"] == key and q["kind"] not in {
                                "needs_review", "duplicate"}
                                             for q in pending),
                            "needs_review": sum(q["collection"] == key and
                                                q["kind"] == "needs_review" for q in pending)})
    return {"workspace_id": revision.workspace_id, "revision_id": revision.id,
            "documents": len({p.document_id for p in revision.documents}),
            "records": sum(c["records"] for c in collections),
            "unsupported_fields": unsupported,
            "conflicts": sum(c["conflicts"] for c in collections),
            "duplicates": sum(c["duplicates"] for c in collections),
            "needs_review": sum(c["needs_review"] for c in collections),
            "accepted_ratio": accepted / total if total else 0.0,
            "updated_at": revision.updated_at or updated_at, "collections": collections}


def answer_revision(base: MergeRevision, question_id: str,
                    answer: CandidateAnswer | DocumentAnswer | EditAnswer | AllAnswer
                    | DuplicateAnswer) -> MergeRevision:
    question = next((q for q in questions(base) if q["id"] == question_id), None)
    if question is None:
        # WP111 (karar 20): a value accepted by a rule stays correctable by its slot ID.
        question = next((q for q in auto_accepted(base) if q["id"] == question_id), None)
    if question is None:
        raise LookupError("question unknown")
    if (question["kind"] == "duplicate") != isinstance(answer, DuplicateAnswer):
        raise ValueError("same answer is required only for a duplicate question")
    revision = base.model_copy(deep=True)
    revision.id = "rev_" + uuid4().hex
    revision.parent_id = base.id
    revision.lineage_id = base.lineage_id or base.id
    revision.updated_at = datetime.now(UTC).isoformat()
    if question["kind"] == "duplicate":
        answer_duplicate(revision, question, answer.same, revision_runtime(base))
        return MergeRevision.model_validate_json(revision.model_dump_json(round_trip=True))
    if question["kind"] in {"schedule_swap", "schedule_conflict"}:
        _answer_schedule(revision, question, answer)
        return MergeRevision.model_validate_json(revision.model_dump_json(round_trip=True))
    record = next(r for r in revision.records if r.id == question["record_id"])
    field = record.fields[question["field"]]
    if question["kind"] == "auto_accepted":
        # Reopen the rule's slot, including its recorded variants; the answer below decides it.
        offered = {option["candidate_id"] for option in question["options"]}
        for candidate in field.candidates:
            if candidate.lang == question["lang"] and candidate.id in offered:
                candidate.review_state = "needs_review"
    all_candidates = []
    if isinstance(answer, (AllAnswer, DocumentAnswer)):
        if isinstance(answer, AllAnswer) and not question["allow_all"]:
            raise ValueError("all is not allowed for this question")
        all_candidates = sorted((c for c in field.candidates if c.lang == question["lang"]
                                 and c.review_state != "rejected" and (
                                     isinstance(answer, AllAnswer) or any(
                                         not isinstance(e, UserEditEvidence) and
                                         e.document_id == answer.document_id
                                         for e in c.evidence))), key=lambda c: c.id)
        if not all_candidates:
            raise ValueError("document outside question")
        chosen = all_candidates[0]
        if len(all_candidates) > 1 and question["lang"] not in field.multi_value_languages:
            field.multi_value_languages.append(question["lang"])
    elif isinstance(answer, EditAnswer):
        value = revision_runtime(base).validate_value(record.type, question["field"], answer.value)
        chosen = FactCandidate(id="fact_" + uuid4().hex, value=value, lang=question["lang"],
                               evidence=[UserEditEvidence(at=revision.updated_at, note=answer.note)])
        field.candidates.append(chosen)
    else:
        chosen = next((c for c in field.candidates if c.id == answer.candidate_id
                       and c.lang == question["lang"] and c.review_state != "rejected"), None)
        if chosen is None:
            raise ValueError("candidate outside question")
    for candidate in field.candidates:
        if candidate.lang == question["lang"]:
            candidate.review_state = "accepted" if (
                candidate is chosen or candidate in all_candidates) else "rejected"
    revision.history.append(AnswerHistory(
        question_id=question_id, record_id=record.id, field=question["field"],
        lang=question["lang"], candidate_id=chosen.id, at=revision.updated_at,
        candidate_ids=[c.id for c in all_candidates], all=isinstance(answer, AllAnswer),
        note=answer.note if isinstance(answer, EditAnswer) else "",
    ))
    # Revalidate every candidate's evidence, including unchanged fields.
    return MergeRevision.model_validate_json(revision.model_dump_json(round_trip=True))


def _answer_schedule(revision, question, answer):
    if not isinstance(answer, DocumentAnswer) or not any(
            option["document_id"] == answer.document_id for option in question["options"]):
        raise ValueError("choose a document program for this schedule question")
    for record_id in question["record_ids"]:
        record = next(r for r in revision.records if r.id == record_id)
        field = record.fields[question["field"]]
        selected = sorted((c for c in field.candidates if c.lang == question["lang"]
                           and c.review_state != "rejected" and any(
                               getattr(e, "document_id", None) == answer.document_id
                               for e in c.evidence)), key=lambda c: c.id)
        if not selected:
            raise ValueError("document outside schedule question")
        if question["lang"] not in field.multi_value_languages:
            field.multi_value_languages.append(question["lang"])
        for candidate in field.candidates:
            if candidate.lang == question["lang"]:
                candidate.review_state = "accepted" if candidate in selected else "rejected"
        revision.history.append(AnswerHistory(
            question_id=question["id"], record_id=record_id, field=question["field"],
            lang=question["lang"], candidate_id=selected[0].id,
            candidate_ids=[c.id for c in selected], at=revision.updated_at, note=""))
