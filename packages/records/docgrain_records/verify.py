"""Engine-independent quotation verification and evidenced document conflicts."""

import json
import re
import unicodedata
from collections import defaultdict

from docgrain_eval.scoring import normalized_value
from pydantic import TypeAdapter, ValidationError

from .model import ModelResponseError
from .models import ExtractionResult, Language, RejectedField, Text
from .runtime import HOSPITALITY


def normalize_quote(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _coalesce_document_records(records, document_lang, runtime=None):
    """One type/name identity per document, with evidenced same-language conflicts."""
    runtime = runtime or HOSPITALITY
    grouped = defaultdict(list)
    for record in records:
        key = record.type, normalize_quote(record.name.value).casefold()
        grouped[key].append(record)
    merged = []
    for same_name in grouped.values():
        if len(same_name) == 1:
            merged.append(same_name[0])
            continue
        model, fields_model = runtime.models[same_name[0].type]
        primary, i18n, conflicts = {}, defaultdict(dict), {}
        for field in fields_model.model_fields:
            candidates = {}
            for record in same_name:
                alternatives = [getattr(record, field)]
                alternatives.extend(getattr(fields, field) for fields in record.i18n.values())
                alternatives.extend(record.conflicts.get(field, []))
                for fact in alternatives:
                    if fact is None:
                        continue
                    signature = (fact.lang, json.dumps(normalized_value(fact.value, field),
                                                       sort_keys=True, ensure_ascii=False))
                    if signature not in candidates:
                        candidates[signature] = fact.model_copy(deep=True)
                    else:
                        seen = {(e.document_id, e.locator, e.quote)
                                for e in candidates[signature].evidence}
                        for evidence in fact.evidence:
                            key = evidence.document_id, evidence.locator, evidence.quote
                            if key not in seen:
                                candidates[signature].evidence.append(evidence.model_copy(deep=True))
                                seen.add(key)
            by_language = defaultdict(list)
            for signature in sorted(candidates):
                by_language[signature[0]].append(candidates[signature])
            languages = sorted(by_language, key=lambda lang: (
                0 if lang == "en" else 1 if lang.split("-")[0] == "en"
                else 2 if lang == document_lang else 3, lang))
            if not languages:
                continue
            primary[field] = by_language[languages[0]][0]
            for language in languages:
                if language.split("-")[0] != "en":
                    i18n[language][field] = by_language[language][0]
                if len(by_language[language]) > 1:
                    conflicts.setdefault(field, []).extend(by_language[language][1:])
        merged.append(model(
            id=min(record.id for record in same_name), **primary,
            i18n={language: fields_model(**fields) for language, fields in i18n.items()},
            conflicts=conflicts,
            review_state="needs_review" if conflicts else "proposed",
        ))
    return merged


def _blocks(context: str) -> dict[str, str]:
    """Resolve compact source keys to block bodies, excluding projection metadata."""
    # Match the whole line: legacy DOCX paths contain inner `]` characters.
    markers = list(re.finditer(r"(?m)^\[§(\d+) p\.[^\r\n]*\]\r?$", context))
    end = re.search(r"(?m)^## Kaynak anahtarları\r?$", context)
    boundary = end.start() if end else len(context)
    blocks = {}
    for index, marker in enumerate(markers):
        stop = markers[index + 1].start() if index + 1 < len(markers) else boundary
        if marker.start() < boundary:
            body = normalize_quote(context[marker.end():min(stop, boundary)])
            blocks[f"§{marker.group(1)}"] = body
            blocks[marker.group().strip()] = body
    # The footer maps source keys to canonical object IDs; allow those as locators too.
    footer = context[boundary:]
    for key, object_id in re.findall(r"(?m)^§(\d+) → (\S+)(?: · [^\r\n]*)?\r?$", footer):
        if f"§{key}" in blocks:
            blocks[object_id] = blocks[f"§{key}"]
    return blocks


def _source_key(locator: str) -> str:
    """Resolve `§N`, `[§N p.X]`, and `§N p.X` to the same source block."""
    match = re.search(r"§\d+", locator)
    return match.group() if match else locator


def verify_response(raw: str, context: str, document_id: str, lang: str,
                    collection: str | None = None, *, source_context: str | None = None,
                    runtime=None) -> ExtractionResult:
    """No model call. Quote checks are exact after NFKC/whitespace normalization."""
    runtime = runtime or HOSPITALITY
    TypeAdapter(Text).validate_python(document_id)
    TypeAdapter(Language).validate_python(lang)
    if not context.strip():
        raise ValueError("source context is empty")
    try:
        proposed = runtime.response.model_validate_json(raw)
    except (ValueError, ValidationError) as exc:
        raise ModelResponseError("model output is not valid collection JSON") from exc
    if collection and any(record.type != collection for record in proposed.records):
        raise ModelResponseError("model output contains a different collection")
    source = normalize_quote(context)
    blocks = _blocks(context)
    original_source = normalize_quote(source_context) if source_context is not None else source
    original_blocks = _blocks(source_context) if source_context is not None else blocks
    records, rejected = [], []
    for index, candidate in enumerate(proposed.records):
        record_model, fields_model = runtime.models[candidate.type]
        primary, i18n = {}, {}
        for field in fields_model.model_fields:
            verified = []
            seen_languages = set()
            for alternative in getattr(candidate, field):
                reason = None
                for evidence in alternative.evidence:
                    quote = normalize_quote(evidence.quote)
                    source_key = _source_key(evidence.locator)
                    if evidence.document_id != document_id:
                        reason = "document_mismatch"
                    elif blocks and source_key not in blocks:
                        reason = "locator_not_found"
                    elif not quote or quote not in blocks.get(source_key, source):
                        reason = "quote_not_found"
                    elif original_blocks and source_key not in original_blocks:
                        reason = "locator_not_found"
                    elif quote not in original_blocks.get(source_key, original_source):
                        # Repeated table headers must not manufacture contiguous quotations.
                        reason = "quote_not_found"
                    if reason:
                        break
                if not reason and alternative.lang in seen_languages:
                    reason = "duplicate_language"
                if reason:
                    rejected.append(RejectedField(
                        record_index=index, record_type=candidate.type, field=field,
                        lang=alternative.lang, reason=reason, evidence=alternative.evidence,
                    ))
                    continue
                seen_languages.add(alternative.lang)
                verified.append(alternative)
                if alternative.lang.split("-")[0] != "en":
                    i18n.setdefault(alternative.lang, {})[field] = alternative
            if verified:
                primary[field] = next((v for v in verified if v.lang.split("-")[0] == "en"),
                                      next((v for v in verified if v.lang == lang), verified[0]))
        # An anonymous remainder is not one identifiable real thing.
        if runtime.identities[candidate.type] in primary:
            records.append(record_model(
                id=f"{document_id}:{candidate.type}:{index + 1}",
                **primary, i18n={key: fields_model(**fields) for key, fields in i18n.items()},
            ))
    return runtime.result(document_id=document_id, lang=lang,
                          records=_coalesce_document_records(records, lang, runtime), rejected=rejected)


