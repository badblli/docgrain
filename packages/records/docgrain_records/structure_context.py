"""Source-derived structure for extraction and conservative identity boundaries.

Compact headings are canonical section projections. API loads additionally pin the
actual ancestor tree in the footer, so sibling containers and section splits cannot
change ownership. Source text and metadata remain data, never prompt instructions.
"""

import json
import re
import unicodedata

from .models import StructureContext, StructureHeading

MARKER = re.compile(r"(?m)^\[§(\d+) p\.[^\r\n]*\]\r?$")
FOOTER = re.compile(r"(?m)^## Kaynak anahtarları\r?$")
# KULLANILMIYOR (karar 18, WP118): STRUCTURE_LINE = re.compile(r"(?m)^§\d+ structure=[^\r\n]*(?:\r?\n|$)")
# WP118: tables also pin Docling's row-header column ("§N table={...}").
STRUCTURE_LINE = re.compile(r"(?m)^§\d+ (?:structure|table)=[^\r\n]*(?:\r?\n|$)")
TABLE_LINE = re.compile(r"(?m)^(§\d+) table=(.+)$")
# Bilingual headings ("Çorba / Soup") may be cited per language segment.
HEADING_SEGMENTS = re.compile(r"\s*[/|·•–—]\s*|\s+-\s+|\s*[()]\s*")


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def without_structure(context):
    """Verifier-only footer lines never reach a model prompt or the section size budget."""
    footer = FOOTER.search(context)
    if footer is None:
        return context
    return context[:footer.start()] + STRUCTURE_LINE.sub("", context[footer.start():])


def heading_cites(title, quote):
    """A heading quote is the whole title or one of its separated language segments."""
    quote = normalized(quote)
    return bool(quote) and (quote == normalized(title) or quote in {
        normalized(part) for part in HEADING_SEGMENTS.split(title) if part.strip()})


def source_key(locator):
    match = re.search(r"§\d+", locator)
    return match.group() if match else locator.partition(" cell=")[0]


class StructureIndex:
    def __init__(self, context):
        self.contexts, self.headings, self.bodies = {}, {}, {}
        footer = FOOTER.search(context)
        boundary = footer.start() if footer else len(context)
        markers = [m for m in MARKER.finditer(context) if m.start() < boundary]
        stack = []
        for index, marker in enumerate(markers):
            key = f"§{marker.group(1)}"
            stop = markers[index + 1].start() if index + 1 < len(markers) else boundary
            body = context[marker.end():stop].strip()
            self.bodies[key] = body
            heading = re.match(r"^(#{1,6})\s+([^\n]+)", body)
            if heading:
                level, title = len(heading.group(1)), heading.group(2).strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                entry = StructureHeading(locator=key, title=title)
                self.headings[key] = entry
                stack.append((level, entry))
            path = [entry for _, entry in stack]
            self.contexts[key] = StructureContext(
                heading_path=path, section_title=path[-1].title if path else None)
        # Canonical ancestry overrides linear heading guesses, including empty paths.
        for key, payload in re.findall(r"(?m)^(§\d+) structure=(.+)$", context[boundary:]):
            if key in self.contexts:
                self.contexts[key] = StructureContext.model_validate_json(payload)
        # WP118: Docling's row-header column per table (canonical TableCell source_attributes.row_header).
        self.tables = {}
        for key, payload in TABLE_LINE.findall(context[boundary:]):
            try:
                pinned = json.loads(payload)
            except ValueError:
                continue
            if isinstance(pinned, dict):
                self.tables[key] = pinned
        self.aliases = dict(re.findall(r"(?m)^(§\d+) → (\S+)", context[boundary:]))
        self.aliases = {object_id: key for key, object_id in self.aliases.items()}

    def key(self, locator):
        key = source_key(locator)
        return self.aliases.get(key, key)

    def at(self, locator, quote=None):
        key = self.key(locator)
        result = self.contexts.get(key, StructureContext()).model_copy(deep=True)
        _, separator, metadata = locator.partition(" cell=")
        if separator or quote is not None:
            cell = None
            if separator:
                try:
                    cell = json.loads(metadata)
                except ValueError:
                    return result
            lines = self.bodies.get(key, "").splitlines()
            for index, line in enumerate(lines[:-1]):
                if not line.startswith("|") or not re.fullmatch(r"\|[ :|\-]+\|", lines[index + 1].strip()):
                    continue
                headers = [c.strip() for c in line.strip("|").split("|")]
                captions = [text.strip() for text in lines[:index]
                            if text.strip() and not text.lstrip().startswith(("#", "|"))]
                if captions:
                    result.section_title = captions[-1]
                rows = []
                for row in lines[index + 2:]:
                    if not row.startswith("|"):
                        break
                    rows.append([c.strip() for c in row.strip("|").split("|")])
                if cell is None and quote:
                    matching = [(r + 1, c + 1) for r, row in enumerate(rows) for c, text in enumerate(row)
                                if normalized(text) == normalized(quote)]
                    if len(matching) == 1:
                        cell = {"row": matching[0][0], "column": matching[0][1]}
                    else:
                        matching_rows = [r + 1 for r, row in enumerate(rows)
                                         if normalized(quote) in normalized(" | ".join(row))]
                        if len(matching_rows) == 1:
                            cell = {"row": matching_rows[0], "column": 1}
                if (isinstance(cell, dict) and type(cell.get("row")) is int
                        and type(cell.get("column")) is int
                        and 1 <= cell["row"] <= len(rows)
                        and 1 <= cell["column"] <= len(headers)
                        and cell["column"] <= len(rows[cell["row"] - 1])):
                    result.table_row, result.table_column = cell["row"], cell["column"]
                    # KULLANILMIYOR (karar 18, WP118): result.row_header = rows[cell["row"] - 1][0]
                    row = rows[cell["row"] - 1]
                    column = self.tables.get(key, {}).get("row_header_column")
                    if type(column) is not int or not 0 <= column < len(row) or not row[column]:
                        column = 0
                    result.row_header = row[column]
                    result.column_header = headers[cell["column"] - 1]
                    break
        return result

    def contains_heading(self, citation, anchors):
        heading = self.headings.get(self.key(citation.locator))
        if heading is None or not heading_cites(heading.title, citation.quote):
            return False
        return bool(anchors) and all(
            any(parent.locator == heading.locator for parent in self.at(e.locator).heading_path)
            for e in anchors)


def pin_structure(context, snapshot):
    """Attach canonical parent paths without changing any evidence body or source key."""
    index = StructureIndex(context)
    nodes = {node["id"]: node for node in snapshot.get("structure", [])}
    root = snapshot.get("root_node_id")
    if root not in nodes:
        return context
    keys = {object_id: key for object_id, key in index.aliases.items()}
    paths = {}

    def visit(node_id, ancestors):
        node = nodes[node_id]
        path = ancestors
        if node.get("kind") == "section" and node.get("heading") and node_id in keys:
            path = [*ancestors, StructureHeading(locator=keys[node_id], title=node["heading"])]
        paths[node_id] = path
        for child in node.get("children", []):
            visit(child, path)

    visit(root, [])
    lines = []
    for object_id, key in keys.items():
        path = paths.get(object_id, [])
        value = StructureContext(heading_path=path, section_title=path[-1].title if path else None)
        lines.append(f"{key} structure={value.model_dump_json(exclude_defaults=True)}")
        column = row_header_column(nodes.get(object_id, {}))
        if column is not None:
            lines.append(f"{key} table=" + json.dumps({"row_header_column": column}))
    return context.rstrip() + "\n" + "\n".join(lines) + "\n"


def header_flags(cell):
    """WP118: Docling's table cell header flags as kept in the canonical snapshot."""
    attributes = (cell or {}).get("source_attributes") or {}
    return {name for name in ("column_header", "row_header", "row_section") if attributes.get(name) is True}


def row_header_column(node):
    """First column Docling flagged as ``row_header`` in a body (non column-header) row, else None."""
    if node.get("kind") != "table":
        return None
    columns = [c for row in node.get("rows") or []
               if not any("column_header" in header_flags(cell) for cell in row)
               for c, cell in enumerate(row) if "row_header" in header_flags(cell)]
    return min(columns) if columns else None


def context_signature(context):
    return (tuple(normalized(h.title) for h in context.heading_path),
            normalized(context.row_header or ""), normalized(context.section_title or ""))


def _context_objects(record):
    contexts = list(record.structure_context)
    if not contexts:
        contexts = [e.structure_context for e in record.name.evidence if e.structure_context is not None]
    return [c for c in contexts if any(context_signature(c))]


def record_contexts(record):
    return sorted({context_signature(c) for c in _context_objects(record)})


def record_documents(record):
    return {e.document_id for e in record.name.evidence}


def _labels(record):
    """Distinguishing structural labels: containing heading titles and table row headers."""
    labels = set()
    for context in _context_objects(record):
        labels.update(normalized(h.title) for h in context.heading_path)
        if context.row_header:
            labels.add(normalized(context.row_header))
    return labels


def structure_vocabulary(records):
    """Per document: every heading title / row header any of its records sits under."""
    vocabulary = {}
    for record in records:
        for document in record_documents(record):
            vocabulary.setdefault(document, set()).update(_labels(record))
    return vocabulary


def contexts_conflict(left, right, vocabulary=None):
    """Same document: differing contexts are different things (floor A vs floor B).

    Across documents headings are not comparable text ("Odalar" in a brochure vs
    "2026 Fiyatları" in a price list). They conflict only when one record sits under a
    label that the other document also has, while the other record does not; e.g. both
    plans have "Alt Kat" and "Çatı Katı" headings. Without a vocabulary the check stays
    conservative (any difference conflicts).
    """
    a, b = record_contexts(left), record_contexts(right)
    if not (a and b and a != b):
        return False
    left_documents, right_documents = record_documents(left), record_documents(right)
    if vocabulary is None or left_documents & right_documents:
        return True
    left_labels, right_labels = _labels(left), _labels(right)
    left_vocabulary = set().union(*(vocabulary.get(d, set()) for d in left_documents))
    right_vocabulary = set().union(*(vocabulary.get(d, set()) for d in right_documents))
    return bool((left_labels - right_labels) & right_vocabulary
                or (right_labels - left_labels) & left_vocabulary)


def identity_context(record, index):
    contexts = [index.at(e.locator, e.quote) for e in record.name.evidence]
    # A repeated name in a table can be disambiguated by a unique factual cell.
    if not any(c.row_header for c in contexts):
        for field in record.field_names():
            fact = getattr(record, field)
            if fact is not None:
                for e in fact.evidence:
                    context = index.at(e.locator, e.quote)
                    if context.row_header:
                        contexts.append(context)
    return contexts
