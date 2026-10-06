"""Offline held-out Record measurement. Source text is data, never instructions.

This module intentionally imports no API or model client. All customer artifacts
belong in an ignored local directory, including the detailed scoring output.
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .golden import load_jsonl
from .scoring import (
    FREE_TEXT_FIELDS,
    KEY_FACT_THRESHOLD,
    key_fact_overlap,
    list_items,
    normalized_value,
    number,
    time_range,
    unit,
)
from .scoring import normalize as answer_normalize
from .taxonomy import load_taxonomy

Collection = Literal[
    "property", "room_type", "outlet", "activity", "facility", "policy", "contact", "service_price"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Evidence(StrictModel):
    document_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class Section(StrictModel):
    locator: str = Field(min_length=1)
    languages: list[str] = Field(min_length=1)
    kind: Literal["text", "table", "image"]
    split: Literal["holdout", "excluded"]
    text: str = Field(min_length=1)


class Source(StrictModel):
    document_id: str = Field(min_length=1)
    source_version_id: str = Field(min_length=1)
    knowledge_revision_id: str | None = None
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    languages: list[str] = Field(min_length=1)
    sections: list[Section] = Field(min_length=1)

    @model_validator(mode="after")
    def section_languages(self):
        if any(not set(section.languages) <= set(self.languages) for section in self.sections):
            raise ValueError("section languages must be declared on the source")
        return self


class Manifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    approved_by: str = Field(min_length=1)
    frozen_at: str | None = None
    sources: list[Source] = Field(min_length=1)
    # Receipts/overlap must come from the earlier keys, not from predictions.
    prior_golden_sha256: list[str]
    overlap: list[Evidence]
    overlap_review_note: str = Field(min_length=1)
    coverage_gaps: list[str]
    available_collections: list[Collection] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sources(self):
        ids = [source.document_id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source document ids")
        for source in self.sources:
            locators = [section.locator for section in source.sections]
            if len(locators) != len(set(locators)):
                raise ValueError("duplicate source locators")
        return self


class ExpectedValue(StrictModel):
    value: Any
    lang: str = Field(min_length=2)
    evidence: list[Evidence] = Field(min_length=1)
    accept: list[Any] = Field(default_factory=list)


class GoldenField(StrictModel):
    id: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    collection: Collection
    field: str = Field(min_length=1)
    primary: ExpectedValue | None
    i18n: dict[str, ExpectedValue] = Field(default_factory=dict)
    # Absence means explicitly checked absent; false/0/empty lists are values.
    absent: bool = False
    conflicts: list[ExpectedValue] = Field(default_factory=list)
    tags: list[Literal["table", "unit", "negative", "missing", "cross_document_conflict"]]
    checked_by: str = Field(min_length=1)
    checked_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_placement(self):
        if self.absent:
            if self.primary is not None or self.i18n or self.conflicts:
                raise ValueError("absent fields cannot have expected values")
        elif self.primary is None or self.primary.value is None:
            raise ValueError("present fields require a primary value")
        for lang, value in self.i18n.items():
            if value.lang != lang or lang.split("-")[0] == "en":
                raise ValueError("i18n placement must preserve non-English language")
        if (self.primary and any(v.lang.split("-")[0] == "en" for v in self.conflicts)
                and self.primary.lang.split("-")[0] != "en"):
            raise ValueError("English candidates require English primary")
        if self.conflicts and len(self.conflicts) < 2:
            raise ValueError("conflicts require at least two visible candidates")
        if self.conflicts and not any(a.lang == b.lang and not equal(a.value, b.value)
                                      for a in self.conflicts for b in self.conflicts):
            raise ValueError("conflict candidates must include differing same-language facts")
        if self.conflicts and self.primary and not any(
            self.primary.lang == candidate.lang and equal(self.primary.value, candidate.value)
            for candidate in self.conflicts
        ):
            raise ValueError("primary value must be one of the conflict candidates")
        return self


class GoldenQuestion(StrictModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answerable: bool
    field_ids: list[str]
    expected: Any
    evidence: list[Evidence]
    # Explicitly unanswerable questions need a human-reviewed source scope/reason.
    document_ids: list[str] = Field(min_length=1)
    absence_reason: str | None = None
    checked_by: str = Field(min_length=1)
    checked_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def answer_shape(self):
        if self.answerable:
            if not self.field_ids or not self.evidence or self.expected is None:
                raise ValueError("answerable question requires fields, answer and evidence")
        elif self.expected is not None or self.evidence or not self.absence_reason:
            raise ValueError("unanswerable question requires null answer and absence reason")
        return self


def normalize(text: str) -> str:
    """No case folding or substring value matching: languages and units matter."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, str):
        return normalize(actual) == normalize(expected)
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(equal(a, e) for a, e in zip(actual, expected))
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(equal(actual[k], v) for k, v in expected.items())
    return actual == expected


def _list_items(value: list) -> list[str]:
    """Treat explicit alternatives in one source list item as separate terms."""
    values = value if isinstance(value, list) else [value]
    # Preserve WP45's list coverage for source conjunctions. Conflict comparison
    # deliberately splits alternatives only: AND does not become OR in the model.
    return list_items([re.sub(r"\b(?:ve|and)\b", ";", answer_normalize(item))
                       if isinstance(item, str) else item for item in values])


def value_match(actual: Any, expected: Any, field: str) -> tuple[bool, tuple[int, int] | None]:
    """Meaning-aware deterministic comparison; list coverage is a diagnostic denominator."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is type(expected) and actual == expected, None
    if isinstance(expected, list):
        if not isinstance(actual, (list, str)):
            return False, (0, len(_list_items(expected)))
        target, predicted = _list_items(expected), _list_items(actual)
        matched = sum(item in predicted for item in target)
        return matched == len(target), (matched, len(target))
    if isinstance(expected, (int, float)):
        return number(actual) == number(expected), None
    if isinstance(expected, str) and isinstance(actual, str):
        if field in FREE_TEXT_FIELDS:
            return key_fact_overlap(actual, expected) >= KEY_FACT_THRESHOLD, None
        expected_range, actual_range = time_range(expected), time_range(actual)
        if expected_range and actual_range and len(re.findall(r"\d{1,2}[:.]\d{2}", expected)) == 2:
            return expected_range == actual_range, None
        if field in {"fee", "currency", "unit"} and unit(expected) and unit(actual):
            if field == "fee":
                return normalized_value(actual, field) == normalized_value(expected, field), None
            return unit(expected) == unit(actual), None
        return normalized_value(actual, field) == normalized_value(expected, field), None
    return equal(actual, expected), None


def _record_names(record: dict) -> list[str]:
    values = record.get("fields", record)
    if not isinstance(values, dict):
        return []
    names = []
    primary = values.get("name")
    if isinstance(primary, dict) and isinstance(primary.get("value"), str):
        names.append(answer_normalize(primary["value"]))
    for fields in record.get("i18n", {}).values():
        if isinstance(fields, dict) and isinstance(fields.get("name"), dict):
            name = fields["name"].get("value")
            if isinstance(name, str):
                names.append(answer_normalize(name))
    return names


def _name_score(predicted: list[str], expected: list[str]) -> float:
    if not predicted or not expected:
        return 0.0
    if predicted[0] == expected[0]:
        return 1.0
    if set(predicted) & set(expected):
        return .98
    best = 0.0
    for left in predicted:
        for right in expected:
            shared = {token for token in re.findall(r"\w+", left) if len(token) >= 4}
            shared &= {token for token in re.findall(r"\w+", right) if len(token) >= 4}
            if shared:
                best = max(best, SequenceMatcher(None, left, right).ratio())
    return best if best >= .55 else 0.0


def align_records(fields: list[GoldenField], records: list[dict]) -> tuple[dict[str, str], list[dict]]:
    """Align by document and name, preferring type before neighbouring types.

    Returns saved-id to golden-id mapping and every tied top candidate. Equal
    scores are resolved by stable ids so a score is reproducible, not hidden.
    """
    grouped = {}
    for field in fields:
        grouped.setdefault(field.record_id, []).append(field)
    expected = {}
    for record_id, record_fields in grouped.items():
        name = next((field for field in record_fields if field.field == "name"), None)
        if name is None:
            continue
        expected[record_id] = (record_fields[0].collection,
                               [answer_normalize(v.value) for v in [name.primary, *name.i18n.values()] if v])
    assigned = {}
    used = set()
    neighbours = load_taxonomy()["collections"]
    for record in records:
        record_id = record["id"]
        if record_id in grouped:
            assigned[record_id] = record_id
            used.add(record_id)
    candidates = []
    by_gold = {}
    by_saved = {}
    for record in records:
        saved_id = record["id"]
        if saved_id in assigned:
            continue
        document_id = record.get("document_id") or saved_id.split(":", 1)[0]
        names = _record_names(record)
        for golden_id, (collection, gold_names) in expected.items():
            same_type = record.get("type") == collection
            if (golden_id in used or golden_id.split(":", 1)[0] != document_id
                    or (not same_type and record.get("type") not in neighbours[collection]["neighbours"])):
                continue
            score = _name_score(names, gold_names)
            if score and (same_type or score >= .75):
                candidates.append((same_type, score, saved_id, golden_id))
                by_gold.setdefault(golden_id, []).append(((same_type, score), saved_id))
                by_saved.setdefault(saved_id, []).append(((same_type, score), golden_id))
    ambiguities = []
    for gold_id, options in by_gold.items():
        top = max(priority for priority, _ in options)
        tied = sorted(saved for priority, saved in options if priority == top)
        if len(tied) > 1:
            ambiguities.append({"golden_id": gold_id, "saved_ids": tied, "score": top[1]})
    for saved_id, options in by_saved.items():
        top = max(priority for priority, _ in options)
        tied = sorted(gold for priority, gold in options if priority == top)
        if len(tied) > 1:
            ambiguities.append({"saved_id": saved_id, "golden_ids": tied, "score": top[1]})
    for _, score, saved_id, golden_id in sorted(
            candidates, key=lambda row: (-row[0], -row[1], row[2], row[3])):
        if saved_id not in assigned and golden_id not in used:
            assigned[saved_id] = golden_id
            used.add(golden_id)
    return assigned, ambiguities


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def source_path(value: str, base: Path) -> Path:
    path = Path(value)
    # Reject these directories before resolving or opening any source file.
    if any(part.casefold() in {"sondb", "yeni db"} for part in path.parts):
        raise ValueError("forbidden source directory")
    resolved = (base / path).resolve()
    if any(part.casefold() in {"sondb", "yeni db"} for part in resolved.parts):
        raise ValueError("forbidden source directory")
    return resolved


def check_sources(manifest: Manifest, base: Path) -> None:
    for source in manifest.sources:
        if digest(source_path(source.path, base)) != source.sha256:
            raise ValueError("source hash differs from frozen manifest")


def sections(manifest: Manifest) -> dict:
    return {(source.document_id, section.locator): section
            for source in manifest.sources for section in source.sections}


def evidence_in_source(evidence: Evidence, manifest: Manifest, holdout: bool = True) -> bool:
    section = sections(manifest).get((evidence.document_id, evidence.locator))
    quote = normalize(evidence.quote)
    return bool(section and quote and (not holdout or section.split == "holdout")
                and quote in normalize(section.text))


def evidence_failure(evidence: Evidence, source_texts: dict[str, list[str]]) -> str | None:
    """Validate a quote against its named original, independent of locator syntax."""
    if evidence.document_id not in source_texts:
        return "evidence_unknown_document"
    quote = answer_normalize(evidence.quote)
    if not any(quote in text for text in source_texts[evidence.document_id]):
        return "evidence_quote_not_in_source"
    return None


def validate_key(manifest: Manifest, fields: list[GoldenField], questions: list[GoldenQuestion]) -> dict:
    if not manifest.frozen_at:
        raise ValueError("holdout sections must be frozen before annotation/prediction inspection")
    try:
        frozen = datetime.fromisoformat(manifest.frozen_at)
        if frozen.utcoffset() is None:
            raise ValueError("freeze timestamp needs timezone")
        for item in [*fields, *questions]:
            checked = datetime.fromisoformat(item.checked_at)
            if checked.utcoffset() is None or checked < frozen:
                raise ValueError("annotation must be checked after holdout freeze")
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid freeze/annotation chronology") from exc
    keys = [(f.record_id, f.field) for f in fields]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate record/field annotations")
    if len({f.id for f in fields}) != len(fields) or len({q.id for q in questions}) != len(questions):
        raise ValueError("duplicate annotation ids")
    collections_by_record = {}
    for field in fields:
        if field.collection not in manifest.available_collections:
            raise ValueError("golden collection is absent from declared available collections")
        if collections_by_record.setdefault(field.record_id, field.collection) != field.collection:
            raise ValueError("one record cannot have multiple collections")
        if "cross_document_conflict" in field.tags:
            conflict_documents = {e.document_id for v in field.conflicts for e in v.evidence}
            if len(conflict_documents) < 2:
                raise ValueError("cross-document conflict requires candidates from multiple documents")
        for value in [field.primary, *field.i18n.values(), *field.conflicts]:
            if value is None:
                continue
            for evidence in value.evidence:
                if not evidence_in_source(evidence, manifest):
                    raise ValueError("golden evidence absent from frozen holdout location")
                if value.lang not in sections(manifest)[(evidence.document_id, evidence.locator)].languages:
                    raise ValueError("golden language absent from annotated source section")
        if "table" in field.tags and not any(
            sections(manifest)[(e.document_id, e.locator)].kind == "table"
            for v in [field.primary, *field.i18n.values(), *field.conflicts] if v for e in v.evidence
        ):
            raise ValueError("table-tagged field requires original table evidence")
    field_ids = {field.id for field in fields}
    supports_by_field = {
        field.id: [e for v in [field.primary, *field.i18n.values(), *field.conflicts] if v for e in v.evidence]
        for field in fields
    }
    document_ids = {source.document_id for source in manifest.sources}
    for question in questions:
        if not set(question.field_ids) <= field_ids or not set(question.document_ids) <= document_ids:
            raise ValueError("question refers to unknown field or source")
        if any(e.document_id not in question.document_ids or not evidence_in_source(e, manifest)
               for e in question.evidence):
            raise ValueError("question evidence absent from frozen holdout location")
        allowed = [e for fid in question.field_ids for e in supports_by_field[fid]]
        if any(not any(e.document_id == a.document_id and e.locator == a.locator
                       and normalize(e.quote) == normalize(a.quote) for a in allowed)
               for e in question.evidence):
            raise ValueError("question evidence does not support the referenced fields")
    for evidence in manifest.overlap:
        if not evidence_in_source(evidence, manifest, holdout=False):
            raise ValueError("overlap evidence absent from source section")
    overlap_keys = {(e.document_id, e.locator) for e in manifest.overlap}
    contaminated = sum(section.split == "holdout" and (source.document_id, section.locator) in overlap_keys
                       for source in manifest.sources for section in source.sections)
    languages = {lang for source in manifest.sources for lang in source.languages}
    covered_languages = {value.lang for field in fields
                         for value in [field.primary, *field.i18n.values(), *field.conflicts] if value}
    tags = {tag for field in fields for tag in field.tags}
    missing_collections = sorted(set(manifest.available_collections) - {f.collection for f in fields})
    missing_languages = sorted(languages - covered_languages)
    unanswerable = sum(not q.answerable for q in questions)
    requirements = {
        "verified_fields_at_least_100": len(fields) >= 100,
        "questions_at_least_40": len(questions) >= 40,
        "unanswerable_at_least_8": unanswerable >= 8,
        "all_available_collections": not missing_collections,
        "all_source_languages": not missing_languages,
        "required_cases": {"table", "unit", "negative", "missing", "cross_document_conflict"} <= tags,
        "no_prior_golden_holdout_overlap": contaminated == 0,
    }
    return {"fields": len(fields), "questions": len(questions), "unanswerable": unanswerable,
            "missing_collections": missing_collections, "missing_languages": missing_languages,
            "overlapping_holdout_sections": contaminated, "requirements": requirements,
            "ready": all(requirements.values()), "coverage_gaps": manifest.coverage_gaps}


def _valid_value(actual: Any, expected: ExpectedValue, field: str,
                 source_texts: dict[str, list[str]]) -> tuple[bool, list[str], tuple[int, int] | None]:
    reasons = []
    if not isinstance(actual, dict):
        return False, ["malformed_field"], None
    if actual.get("lang") != expected.lang:
        reasons.append("wrong_language")
    comparisons = [value_match(actual.get("value"), value, field) for value in [expected.value, *expected.accept]]
    matched = next((coverage for ok, coverage in comparisons if ok), None)
    coverage = matched if any(ok for ok, _ in comparisons) else comparisons[0][1]
    if not any(ok for ok, _ in comparisons):
        reasons.append("wrong_value")
    raw_evidence = actual.get("evidence")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        reasons.append("missing_evidence")
    else:
        for raw in raw_evidence:
            try:
                evidence = Evidence.model_validate(raw)
            except ValueError:
                reasons.append("invalid_evidence")
                continue
            failure = evidence_failure(evidence, source_texts)
            if failure:
                reasons.append("invalid_evidence")
                reasons.append(failure)
    return not reasons, sorted(set(reasons)), coverage


def _slots(record: dict) -> dict:
    """WP41 flat fields or explicit offline adapter fields; nulls are absent."""
    values = record.get("fields", record)
    if not isinstance(values, dict) or not isinstance(record.get("i18n", {}), dict):
        raise TypeError("malformed record fields/i18n")
    metadata = {"id", "type", "review_state", "i18n", "conflicts", "fields"}
    result = {(None, field): value for field, value in values.items()
              if field not in metadata and value is not None}
    for lang, fields in record.get("i18n", {}).items():
        if not isinstance(fields, dict):
            raise TypeError("malformed i18n fields")
        result.update({(lang, field): value for field, value in fields.items() if value is not None})
    return result


def score_records(manifest: Manifest, fields: list[GoldenField], records: list[dict],
                  contexts: dict[str, str] | None = None) -> dict:
    """Each expected field counts once; i18n/conflicts are required for correctness.

    Extra predictions outside the held-out key are unassessed, not unsupported.
    """
    source_texts = {source.document_id: [answer_normalize(section.text) for section in source.sections]
                    for source in manifest.sources}
    for document_id, context in (contexts or {}).items():
        if document_id not in source_texts:
            raise ValueError("context document is absent from manifest")
        source_texts[document_id].append(answer_normalize(context))
    if any(not isinstance(record, dict) or not isinstance(record.get("id"), str) for record in records):
        raise TypeError("record must have a string id")
    alignment, ambiguities = align_records(fields, records)
    by_id = {}
    saved_ids = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise TypeError("record must have a string id")
        record_id = alignment.get(record["id"], record["id"])
        if record_id in by_id:
            raise ValueError("duplicate predicted record id; merge or explicitly map identities first")
        by_id[record_id] = record
        saved_ids[record_id] = record["id"]
    actual_slots = {rid: _slots(record) for rid, record in by_id.items()}
    for record in by_id.values():
        if not isinstance(record.get("conflicts", {}), dict):
            raise TypeError("conflicts must be an explicit field mapping")
    rows, supported_slots = [], set()
    expected_slots = set()
    annotated_absences = set()
    for field in fields:
        record = by_id.get(field.record_id, {})
        slots = actual_slots.get(field.record_id, {})
        reasons = []
        if record and record.get("type") != field.collection:
            reasons.append("wrong_collection")
        expected = {(None, field.field): field.primary} if field.primary else {}
        expected.update({(lang, field.field): value for lang, value in field.i18n.items()})
        examples = []
        list_matched = list_expected = 0
        if field.absent:
            annotated_absences.add((field.record_id, field.field))
            if any(key[1] == field.field for key in slots):
                reasons.append("unexpected_present")
        else:
            for key, value in expected.items():
                identity = (field.record_id, *key)
                expected_slots.add(identity)
                if key not in slots:
                    reasons.append("omitted_primary" if key[0] is None else "omitted_i18n")
                    if isinstance(value.value, list):
                        list_expected += len(_list_items(value.value))
                    continue
                ok, failures, coverage = _valid_value(slots[key], value, field.field, source_texts)
                reasons.extend(failures)
                if coverage is not None:
                    list_matched += coverage[0]
                    list_expected += coverage[1]
                if "wrong_value" in failures:
                    examples.append({"lang": key[0] or "primary", "expected": value.value,
                                     "actual": slots[key].get("value") if isinstance(slots[key], dict) else slots[key]})
                if (key[0] is None and value.lang.split("-")[0] == "en"
                        and (not isinstance(slots[key], dict)
                             or str(slots[key].get("lang", "")).split("-")[0] != "en")):
                    reasons.append("en_first_error")
                if ok and record.get("type") == field.collection:
                    supported_slots.add(identity)
        conflicts = record.get("conflicts", {})
        if not isinstance(conflicts, dict):
            raise TypeError("conflicts must be an explicit field mapping")
        actual_conflict = conflicts.get(field.field)
        if field.conflicts:
            # A conflict is visible only with its candidates and an unresolved state.
            candidates = actual_conflict.get("candidates", []) if isinstance(actual_conflict, dict) else []
            if not isinstance(candidates, list) or len(candidates) != len(field.conflicts):
                reasons.append("hidden_conflict")
            else:
                remaining = list(candidates)
                for expected_candidate in field.conflicts:
                    match = next((i for i, candidate in enumerate(remaining)
                                  if _valid_value(candidate, expected_candidate, field.field, source_texts)[0]), None)
                    if match is None:
                        reasons.append("wrong_conflict_candidate")
                    else:
                        remaining.pop(match)
            if not isinstance(actual_conflict, dict) or actual_conflict.get("review_state") != "needs_review":
                reasons.append("hidden_conflict")
        elif actual_conflict:
            reasons.append("unexpected_conflict")
        rows.append({"id": field.id, "record_id": field.record_id,
                     "saved_id": saved_ids.get(field.record_id), "field": field.field,
                     "collection": field.collection, "correct": not reasons,
                     "type_mismatch": bool(record and record.get("type") != field.collection),
                     "content_correct": not (set(reasons) - {"wrong_collection"}),
                     "reasons": sorted(set(reasons)), "wrong_value_examples": examples,
                     "list_items_matched": list_matched, "list_items_expected": list_expected,
                     "list_coverage": list_matched / list_expected if list_expected else None})
    predicted = {(rid, *key) for rid, slots in actual_slots.items() for key in slots}
    annotated_predicted = {slot for slot in predicted
                           if slot in expected_slots or (slot[0], slot[2]) in annotated_absences}
    out_of_key = predicted - annotated_predicted
    unsupported = annotated_predicted - supported_slots
    annotated_conflicts = {(field.record_id, field.field) for field in fields if field.conflicts}
    out_of_key_conflicts = [(rid, field) for rid, record in by_id.items()
                            for field, conflict in record.get("conflicts", {}).items()
                            if conflict and (rid, field) not in annotated_conflicts]

    def summarize(selected):
        failures = Counter(reason for row in selected for reason in row["reasons"])
        correct = sum(row["correct"] for row in selected)
        return {"expected_fields": len(selected), "correct_fields": correct,
                "content_correct_fields": sum(row["content_correct"] for row in selected),
                "type_mismatch_fields": sum(row["type_mismatch"] for row in selected),
                "type_mismatch_records": len({row["record_id"] for row in selected if row["type_mismatch"]}),
                "correctness": correct / len(selected) if selected else None,
                "omitted_fields": sum(any(r.startswith("omitted_") for r in row["reasons"])
                                      for row in selected), "failures": dict(sorted(failures.items())),
                "list_items_matched": sum(row["list_items_matched"] for row in selected),
                "list_items_expected": sum(row["list_items_expected"] for row in selected),
                "list_coverage": (sum(row["list_items_matched"] for row in selected)
                                  / sum(row["list_items_expected"] for row in selected)
                                  if sum(row["list_items_expected"] for row in selected) else None)}

    overall = summarize(rows)
    overall.update({"predicted_slots": len(predicted), "annotated_predicted_slots": len(annotated_predicted),
                    "correct_supported_slots": len(supported_slots),
                    "expected_present_slots": len(expected_slots),
                    "precision": len(supported_slots) / len(annotated_predicted) if annotated_predicted else None,
                    "recall": len(supported_slots) / len(expected_slots) if expected_slots else None,
                    "unsupported_slots": len(unsupported), "out_of_key_slots": len(out_of_key)})
    overall["out_of_key_conflicts"] = len(out_of_key_conflicts)
    target_met = (overall["correctness"] is not None and overall["correctness"] >= .95
                  and not unsupported and not ambiguities)
    per_collection = {}
    for collection in sorted({f.collection for f in fields} | {r.get("type", "unknown") for r in records}):
        metrics = summarize([r for r in rows if r["collection"] == collection])
        collection_slots = {slot for slot in predicted if by_id[slot[0]].get("type", "unknown") == collection}
        supported = len(collection_slots & supported_slots)
        metrics.update({"predicted_slots": len(collection_slots), "correct_supported_slots": supported,
                        "annotated_predicted_slots": len(collection_slots & annotated_predicted),
                        "precision": supported / len(collection_slots & annotated_predicted)
                        if collection_slots & annotated_predicted else None,
                        "unsupported_slots": len(collection_slots & unsupported),
                        "out_of_key_slots": len(collection_slots & out_of_key)})
        per_collection[collection] = metrics
    return {"overall": overall,
            "per_collection": per_collection,
            "d4_target": {"minimum_correctness": .95, "maximum_unsupported_slots": 0,
                          "measurement_met": target_met},
            "fields": rows,
            "alignment": [{"saved_id": saved_id, "golden_id": golden_id}
                          for saved_id, golden_id in sorted(alignment.items())],
            "ambiguous_name_matches": ambiguities,
            "type_mismatches": [{"saved_id": saved_ids[rid], "golden_id": rid,
                                 "expected_collection": next(f.collection for f in fields if f.record_id == rid),
                                 "actual_collection": by_id[rid]["type"]}
                                for rid in sorted({r["record_id"] for r in rows if r["type_mismatch"]})],
            "extra_slots": [{"record_id": rid, "lang": lang, "field": field}
                            for rid, lang, field in sorted(out_of_key, key=str)],
            "extra_conflicts": [{"record_id": rid, "field": field} for rid, field in out_of_key_conflicts]}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--manifest", type=Path, required=True)
    freeze.add_argument("--out", type=Path, required=True)
    for command in ("validate", "score"):
        sub = commands.add_parser(command)
        sub.add_argument("--manifest", type=Path, required=True)
        sub.add_argument("--golden", type=Path, required=True)
        sub.add_argument("--questions", type=Path, required=True)
        if command == "score":
            sub.add_argument("--records", type=Path, nargs="+", required=True)
            sub.add_argument("--context", action="append", default=[], metavar="DOCUMENT_ID=PATH")
            sub.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = Manifest.model_validate(_json(args.manifest))
        check_sources(manifest, args.manifest.parent)
        if args.command == "freeze":
            if manifest.frozen_at or args.out.exists():
                raise ValueError("freeze refuses a frozen manifest or an existing output")
            manifest.frozen_at = datetime.now(UTC).isoformat()
            # Relative source paths stay relative to the input manifest directory.
            for source in manifest.sources:
                source.path = str(source_path(source.path, args.manifest.parent))
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("x", encoding="utf-8") as stream:
                stream.write(manifest.model_dump_json(indent=2) + "\n")
            print("Holdout manifest frozen; annotate originals before reading predictions.")
            return 0
        fields = load_jsonl(args.golden, GoldenField)
        questions = load_jsonl(args.questions, GoldenQuestion)
        coverage = validate_key(manifest, fields, questions)
        if args.command == "validate":
            # Do not print free-text coverage gaps or any customer facts.
            print(json.dumps({k: v for k, v in coverage.items() if k != "coverage_gaps"}))
            return 0 if coverage["ready"] else 2
        records = []
        for path in args.records:
            artifact = _json(path)
            batch = artifact.get("records") if isinstance(artifact, dict) else artifact
            if not isinstance(batch, list):
                raise TypeError("saved records must be a list or a records envelope")
            records.extend(batch)
        contexts = {}
        context_receipts = {}
        for item in args.context:
            document_id, separator, path_text = item.partition("=")
            if not separator or not document_id or not path_text or document_id in contexts:
                raise ValueError("context requires a unique DOCUMENT_ID=PATH")
            path = Path(path_text)
            contexts[document_id] = path.read_text(encoding="utf-8")
            context_receipts[document_id] = digest(path)
        report = score_records(manifest, fields, records, contexts)
        report["coverage"] = coverage
        report["receipts"] = {"manifest_sha256": digest(args.manifest),
                              "golden_sha256": digest(args.golden),
                              "questions_sha256": digest(args.questions),
                              "records_sha256": [digest(path) for path in args.records],
                              "contexts_sha256": context_receipts}
        report["d4_target"]["criteria_met"] = coverage["ready"] and report["d4_target"]["measurement_met"]
        if args.out.exists():
            raise ValueError("output directory already exists; preserve earlier measurement")
        args.out.mkdir(parents=True)
        _write(args.out / "summary.json", {k: v for k, v in report.items()
                                          if k not in {"fields", "extra_slots", "extra_conflicts"}})
        _write(args.out / "extras.json", {"slots": report["extra_slots"], "conflicts": report["extra_conflicts"]})
        (args.out / "fields.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in report["fields"]), encoding="utf-8")
        lines = ["# Offline record measurement", "", json.dumps(report["overall"], indent=2), "",
                 "D4 criteria met: " + str(report["d4_target"]["criteria_met"]), ""]
        lines.extend(f"{name}: {json.dumps(counts)}" for name, counts in report["per_collection"].items())
        (args.out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(json.dumps(report["overall"]))
        return 0 if report["d4_target"]["criteria_met"] else 2
    except (ValueError, OSError, TypeError) as exc:
        # Validation errors can contain private input values. Print only a class.
        print(f"Offline evaluation failed ({type(exc).__name__}); check local inputs.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
