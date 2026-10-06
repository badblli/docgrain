"""Deterministic structural candidates; these never choose industry schemas."""

import re
from collections import defaultdict

from .models import Evidence

MARKER = re.compile(r"(?m)^\[§(\d+) p\.[^\r\n]*\]\r?$")
MEASURES = re.compile(
    r"\b\d{1,2}:\d{2}\b|\b\d+(?:[.,]\d+)?\s*(?:m²|m2|kg|ml|cm|minutes?|mins?|"
    r"hours?|hrs?|dakika|saat|EUR|USD|TRY|TL)\b|[€$₺]\s*\d+(?:[.,]\d+)?",
    re.IGNORECASE,
)


def source_blocks(context):
    """Only compact source bodies, never filenames or the locator footer."""
    boundary = re.search(r"(?m)^## Kaynak anahtarları\r?$", context)
    context = context[:boundary.start()] if boundary else context
    markers = list(MARKER.finditer(context))
    return [(f"§{marker.group(1)}", context[marker.end():
             markers[index + 1].start() if index + 1 < len(markers) else len(context)].strip())
            for index, marker in enumerate(markers)]


def section_title(body):
    """Recognize Markdown and plain/OCR headings without an industry vocabulary."""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return None
    first = lines[0]
    heading = re.fullmatch(r"#{1,6}\s+(.+)", first)
    if heading:
        return heading.group(1).strip()
    if (len(first) <= 100 and any(char.isalpha() for char in first)
            and not re.search(r"[:.!?;|]", first)
            and not re.match(r"(?:[-*•]|\d+[.)])\s", first)):
        return first
    return None


def content_blocks(documents):
    """Every locatable body, including prose and noisy OCR, in stable source order."""
    result = []
    for document in sorted(documents, key=lambda item: item.source.document_id):
        title = None
        for locator, body in source_blocks(document.context):
            title = section_title(body) or title
            if body:
                result.append({"document_id": document.source.document_id, "locator": locator,
                               "title": title or locator, "text": body})
    return result


def field_blocks(body):
    """Repeated cards may be contiguous, separated by blanks, or under distinct headings."""
    for segment in re.split(r"\n\s*\n|\n(?=#{1,6}\s)", body):
        matches = list(re.finditer(r"(?m)^\s*([^:\n]{1,60}):\s*\S.*$", segment))
        labels, start = [], 0
        for match in matches:
            label = match.group(1).strip().casefold()
            if label in labels:
                if len(labels) >= 2:
                    yield " | ".join(sorted(labels)), segment[start:match.start()].strip()
                labels, start = [], match.start()
            labels.append(label)
        if len(labels) >= 2:
            yield " | ".join(sorted(labels)), segment[start:].strip()


def detect_signals(documents):
    """Return complete counts plus a small set of quoted, locatable samples per pattern."""
    groups = defaultdict(list)

    def add(kind, signature, document_id, locator, quote):
        groups[(kind, signature)].append(Evidence(
            document_id=document_id, locator=locator, quote=quote,
        ).model_dump())

    for document in sorted(documents, key=lambda item: item.source.document_id):
        document_id = document.source.document_id
        for locator, body in source_blocks(document.context):
            if not body:
                continue
            title = section_title(body)
            # Singleton sections are useful candidates too; repetition may be semantic,
            # or split into short OCR blocks rather than visible rows/cards.
            add("section_text", title or locator, document_id, locator, body)
            if title:
                add("heading", title.casefold(), document_id, locator, body)
            lines = body.splitlines()
            rows = [line for line in lines if line.strip().startswith("|")
                    and line.strip().endswith("|")]
            rows = [line for line in rows if not re.fullmatch(r"[\s|:\-]+", line)]
            if len(rows) >= 2:
                columns = tuple(cell.strip().casefold() for cell in rows[0].strip(" |").split("|"))
                width = len(columns)
                matching_rows = [row for row in rows[1:]
                                 if len(row.strip(" |").split("|")) == width]
                if width >= 2 and len(matching_rows) >= 2:
                    for row in matching_rows:
                        add("table", " | ".join(columns), document_id, locator, row)
                # Transposed tables: columns identify items, rows identify their fields.
                if width >= 3 and matching_rows:
                    field_names = " | ".join(row.strip(" |").split("|")[0].strip().casefold()
                                             for row in matching_rows)
                    for _ in columns[1:]:
                        add("table_columns", field_names, document_id, locator, body)
            for line in lines:
                label = re.fullmatch(r"\s*([^:\n]{1,60}):\s*\S.*", line)
                if label and not re.match(r"\s*(?:[-*•]|\d+[.)])\s", line):
                    add("label_value", label.group(1).strip().casefold(), document_id, locator, line)
                if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+\S", line):
                    # Similar item shape: replace numbers and field values, retain field labels.
                    item = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line)
                    labels = re.findall(r"(?:^|[;|])\s*([^\d:;|]+):", item)
                    shape = ":".join(label.strip().casefold() for label in labels)
                    if len(labels) == 1:
                        shape = "named_items"
                    pattern = shape or "items"
                    add("list", f"{title.casefold()} | {pattern}" if title else pattern,
                        document_id, locator, line)
                for measure in MEASURES.finditer(line):
                    signature = re.sub(r"\d+(?:[.,]\d+)?", "#", measure.group()).casefold()
                    add("measure", signature, document_id, locator, line)
            for signature, block in field_blocks(body):
                add("fields", signature, document_id, locator, block)
            headings = re.findall(r"(?m)^#{1,6}\s+(.+)$", body)
            for heading in headings:
                if heading.strip() != title:
                    add("heading", heading.strip().casefold(), document_id, locator, body)
    return [{"kind": kind, "pattern": pattern, "count": len(samples),
             "document_ids": sorted({sample["document_id"] for sample in samples}),
             "samples": samples[:6]}
            for (kind, pattern), samples in sorted(groups.items())
            if len(samples) >= 2 or kind in {"heading", "section_text"}]
