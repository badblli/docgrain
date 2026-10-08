"""Engine-independent quotation verification and evidenced document conflicts."""

import json
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal
from typing import Literal, get_args, get_origin

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


def _blocks(context: str, *, normalize: bool = True) -> dict[str, str]:
    """Resolve compact source keys to block bodies, excluding projection metadata."""
    # Match the whole line: legacy DOCX paths contain inner `]` characters.
    markers = list(re.finditer(r"(?m)^\[§(\d+) p\.[^\r\n]*\]\r?$", context))
    end = re.search(r"(?m)^## Kaynak anahtarları\r?$", context)
    boundary = end.start() if end else len(context)
    blocks = {}
    for index, marker in enumerate(markers):
        stop = markers[index + 1].start() if index + 1 < len(markers) else boundary
        if marker.start() < boundary:
            body = context[marker.end():min(stop, boundary)].strip()
            if normalize:
                body = normalize_quote(body)
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
    locator = locator.partition(" cell=")[0]
    match = re.search(r"§\d+", locator)
    return match.group() if match else locator


def _value_spans(text, value):
    """Literal, whole-token values; numeric spelling may use decimal comma/zeroes.

    All list members must occur. No translation, boolean inference or unit conversion.
    NFKC is applied by the caller, including to source superscripts and fullwidth digits.
    """
    spans = []
    for component in value if isinstance(value, list) else [value]:
        if isinstance(component, int | float) and not isinstance(component, bool):
            matches = [m for m in re.finditer(r"(?<![\w.,+\-])[-+]?\d+(?:[.,]\d+)?(?![\w.,]\d|\w)", text)
                       if Decimal(m.group().replace(",", ".")) == Decimal(str(component))]
        else:
            literal = json.dumps(component) if isinstance(component, bool) else str(component)
            matches = list(re.finditer(r"(?<!\w)" + re.escape(normalize_quote(literal)) + r"(?!\w)", text))
        if not matches:
            return []
        spans.extend((m.start(), m.end()) for m in matches)
    return spans


def _context_tokens(text, spans):
    """Complete Unicode words or unit symbols disjoint from the value."""
    return [m for m in re.finditer(r"\w+|[€$£₺₽%°]", text)
            if (any(c.isalpha() for c in m.group()) or m.group() in "€$£₺₽%°")
            and not any(m.start() < end and m.end() > start for start, end in spans)]


_CLOCK = re.compile(r"\d{1,2}[:.]\d{2}(?:\s*[-–—]\s*\d{1,2}[:.]\d{2})?")
_DATE = re.compile(r"(?:\d{1,4}[./-]){2}\d{1,4}|\d{1,2}\s+[^\W\d_]+\s+\d{4}"
                   r"|[^\W\d_]+\s+\d{1,2},?\s+\d{4}")
_NUMBER_WITH_UNIT = re.compile(r"(?:[$€£₺₽]|[A-Z]{3})?\s*[+\-]?\d+(?:[.,]\d+)?"
                               r"(?:\s*(?:[%€$£₺₽]|[^\W\d_]+\d*))?")
_CATEGORICAL_FIELDS = {"category", "kind", "type", "status", "state",
                       "currency", "unit", "availability"}


def _needs_label(field, value, fields_model, identity):
    """Only compact, label-dependent values need context outside themselves.

    Identity and prose/list values with letters are self-identifying. Literal
    choices and category-like field keys stay label-dependent even as strings.
    """
    if isinstance(value, bool | int | float):
        return True
    if isinstance(value, str):
        normalized = normalize_quote(value)
        if (_CLOCK.fullmatch(normalized) or _DATE.fullmatch(normalized)
                or _NUMBER_WITH_UNIT.fullmatch(normalized)):
            return True
    if field == identity:
        return False
    if isinstance(value, list):
        return not value or any(_needs_label(field, item, fields_model, identity) for item in value)
    annotation = get_args(fields_model.model_fields[field].annotation)[0]
    if get_origin(annotation.model_fields["value"].annotation) is Literal:
        return True
    if field in _CATEGORICAL_FIELDS:
        return True
    return not any(c.isalpha() for c in normalize_quote(value))


def _boolean_label(quote, body, field, value):
    """A boolean may cite its written field label without the JSON literal.

    One-word labels must match the field key (and imply presence/true); longer
    phrases can carry a source-language label and qualifier on the same line.
    This is lexical evidence, not a translation or truth-value inference.
    """
    words = [m.group() for m in re.finditer(r"\w+", quote) if any(c.isalpha() for c in m.group())]
    field_label = normalize_quote(field.replace("_", " ")).casefold()
    if not ((value is True and quote.casefold() == field_label) or len(words) >= 2):
        return False
    pattern = r"(?<!\w)" + re.escape(quote) + r"(?!\w)"
    return any(re.search(pattern, normalize_quote(line)) for line in body.splitlines())


def _labelled_quote(quote, body, value):
    """A quote must contain value AND context together on an original source line.

    Larger, multiline quotes remain valid when one included line proves the field;
    whitespace normalization must never join a bare value to a neighbouring label.
    """
    lines = [normalize_quote(line) for line in body.splitlines() if line.strip()]
    source = " ".join(lines)
    for match in re.finditer(re.escape(quote), source):
        offset = 0
        for line in lines:
            start, end = max(0, match.start() - offset), min(len(line), match.end() - offset)
            fragment = line[start:max(start, end)]
            spans = _value_spans(fragment, value)
            original_spans = _value_spans(line, value)
            if (spans and original_spans
                    and all((start + a, start + b) in original_spans for a, b in spans)
                    and any(start <= token.start() and token.end() <= end
                            for token in _context_tokens(line, original_spans))):
                return True
            offset += len(line) + 1
    return False


def _widen_quote(quote, body, value):
    """Smallest complete context token span, with label:value clauses kept intact.

    A colon-labelled clause (delimited by semicolon/pipe or line end) is atomic:
    retaining its label and unit prevents a repair from discarding the field label.
    Other spans include the original quote and one whole non-value word. Ties use
    source order. A model quote already spanning lines can keep that span when
    its value and the added context are together on one of those lines.
    """
    candidates = []
    for index, raw_line in enumerate(body.splitlines()):
        line = normalize_quote(raw_line)
        for match in re.finditer(re.escape(quote), line):
            spans = _value_spans(line, value)
            if not spans:
                continue
            left = max(line.rfind(";", 0, match.start()), line.rfind("|", 0, match.start())) + 1
            right = min((p for p in (line.find(";", match.end()), line.find("|", match.end())) if p >= 0),
                        default=len(line))
            clause = line[left:right].strip()
            label, colon, _ = clause.partition(":")
            if colon and any(c.isalpha() for c in label) and line.find(":", left, right) < match.start():
                options = [(left, right)]
            else:
                options = [(min(match.start(), token.start()), max(match.end(), token.end()))
                           for token in _context_tokens(line, spans)]
            for start, end in options:
                widened = line[start:end].strip()
                if _labelled_quote(widened, line, value):
                    candidates.append((len(widened), index, start, widened))
    lines = [normalize_quote(line) for line in body.splitlines() if line.strip()]
    joined = " ".join(lines)
    offsets = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line) + 1
    for match in re.finditer(re.escape(quote), joined):
        if any(offset <= match.start() and match.end() <= offset + len(line)
               for offset, line in zip(offsets, lines, strict=True)):
            continue
        for index, (offset, line) in enumerate(zip(offsets, lines, strict=True)):
            start, end = max(0, match.start() - offset), min(len(line), match.end() - offset)
            spans = _value_spans(line, value)
            if start < end and any(start <= a and b <= end for a, b in spans):
                left = max(line.rfind(";", 0, start), line.rfind("|", 0, start)) + 1
                label, colon, _ = line[left:start].partition(":")
                if colon and any(c.isalpha() for c in label):
                    options = [(offset + left, match.end())]
                else:
                    options = [(min(match.start(), offset + token.start()),
                                max(match.end(), offset + token.end()))
                               for token in _context_tokens(line, spans)]
                for begin, stop in options:
                    widened = joined[begin:stop].strip()
                    if _labelled_quote(widened, body, value):
                        candidates.append((len(widened), index, begin, widened))
    return min(candidates)[-1] if candidates else None


def _table_header(quote, body, value, locator):
    """Allow a bare Markdown cell only with a source-checked header in its locator.

    Syntax: §N cell={"row":1,"column":2,"column_header":"Size"}.
    Row/column are one-based (row counts data rows); row_header refers to the
    first cell in that data row. A fabricated or unrelated header never qualifies.
    """
    _, separator, metadata = locator.partition(" cell=")
    if not separator:
        return False
    try:
        cell = json.loads(metadata)
    except ValueError:
        return False
    if (not isinstance(cell, dict) or set(cell) - {"row", "column", "row_header", "column_header"}
            or type(cell.get("row")) is not int or type(cell.get("column")) is not int
            or cell["row"] < 1 or cell["column"] < 1):
        return False
    lines = [normalize_quote(line) for line in body.splitlines() if line.strip()]
    for index in range(len(lines) - 1):
        if not lines[index].startswith("|") or not re.fullmatch(r"\|[ :|\-]+\|", lines[index + 1]):
            continue
        rows = []
        for line in lines[index + 2:]:
            if not line.startswith("|"):
                break
            rows.append([c.strip() for c in line.strip("|").split("|")])
        headers = [c.strip() for c in lines[index].strip("|").split("|")]
        row, column = cell["row"] - 1, cell["column"] - 1
        if row >= len(rows) or column >= len(headers) or len(rows[row]) != len(headers):
            continue
        text = rows[row][column]
        if text != quote or not _value_spans(text, value) or _context_tokens(text, _value_spans(text, value)):
            continue
        supplied = {key: cell[key] for key in ("row_header", "column_header") if key in cell}
        expected = {"row_header": rows[row][0], "column_header": headers[column]}
        if supplied and all(isinstance(header, str) and normalize_quote(header) == expected[key]
                            and _context_tokens(expected[key], _value_spans(expected[key], value))
                            for key, header in supplied.items()):
            return True
    return False


def verify_response(raw: str, context: str, document_id: str, lang: str,
                    collection: str | None = None, *, source_context: str | None = None,
                    runtime=None) -> ExtractionResult:
    """No model call. Require source-backed value and same-line lexical context."""
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
    source_lines = _blocks(context, normalize=False)
    original_lines = _blocks(source_context, normalize=False) if source_context is not None else source_lines
    records, rejected = [], []
    for index, candidate in enumerate(proposed.records):
        record_model, fields_model = runtime.models[candidate.type]
        primary, i18n = {}, {}
        for field in fields_model.model_fields:
            verified = []
            seen_languages = set()
            for alternative in getattr(candidate, field):
                reason = None
                repaired = []
                for evidence in alternative.evidence:
                    quote = normalize_quote(evidence.quote)
                    accepted_quote = evidence.quote
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
                    else:
                        body = original_lines.get(source_key, source_context if source_context is not None else context)
                        projected_body = source_lines.get(source_key, context)
                        boolean_label = (isinstance(alternative.value, bool)
                                         and _boolean_label(quote, body, field, alternative.value)
                                         and _boolean_label(quote, projected_body, field, alternative.value))
                        if (not boolean_label and (not _value_spans(quote, alternative.value)
                                or not _value_spans(blocks.get(source_key, source), alternative.value)
                                or not _value_spans(original_blocks.get(source_key, original_source),
                                                    alternative.value))):
                            reason = "value_not_in_quote"
                        elif not boolean_label and _needs_label(
                                field, alternative.value, fields_model, runtime.identities[candidate.type]):
                            labelled = (_labelled_quote(quote, body, alternative.value)
                                        and _labelled_quote(quote, projected_body, alternative.value))
                            table_cell = (_table_header(quote, body, alternative.value, evidence.locator)
                                          and _table_header(quote, projected_body, alternative.value, evidence.locator))
                            if not labelled and not table_cell:
                                widened = _widen_quote(quote, body, alternative.value)
                                if widened and _labelled_quote(widened, projected_body, alternative.value):
                                    accepted_quote = widened
                                else:
                                    reason = "bare_value_quote"
                    if reason:
                        break
                    repaired.append(evidence.model_copy(update={"quote": accepted_quote}))
                if not reason and alternative.lang in seen_languages:
                    reason = "duplicate_language"
                if reason:
                    rejected.append(RejectedField(
                        record_index=index, record_type=candidate.type, field=field,
                        lang=alternative.lang, reason=reason, evidence=alternative.evidence,
                    ))
                    continue
                alternative = alternative.model_copy(update={"evidence": repaired})
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


