"""TXT structure from Docling's Markdown backend, text from the original file (WP118).

Docling 2.130 lists ``txt`` under ``InputFormat.MD`` and reads it with ``MarkdownDocumentBackend``. That
backend gives the structure we want (``TitleItem``/``SectionHeaderItem`` headings, ``ListGroup``/``ListItem``,
``TableItem`` with ``column_header`` cells), but it rewrites text: emphasis markers (``*``, ``_``) are dropped,
inline formatting splits one paragraph into several ``TextItem`` children of an ``InlineGroup``, link targets and
HTML tags disappear, escapes are resolved and soft line breaks become spaces. Its items carry no character
provenance either.

So Docling is used only for structure. Each Docling block (heading, list item, paragraph, table) is aligned to
the original text by its words, in reading order, and its canonical text is the exact original substring of the
lines it covers (minus the heading ``#``, bullet ``-``/``*``/``+`` and quote ``>`` markers; ordered-list numbers
are kept because they can carry meaning, e.g. "1. Kat"). Source lines that no Docling block covers stay as exact
paragraphs, so no source word is ever lost. Pure functions: no Docling import here.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from .structural import TABLE_HEADER_FLAGS

WORD = re.compile(r"\w+")
WINDOW = 400  # source words a block may skip (link targets, HTML tags) before its next word
_ATX = re.compile(r"^(#{1,6})(?:[ \t]+|$)")
_BULLET = re.compile(r"^[-*+][ \t]+")
_QUOTE = re.compile(r"^>[ \t]?")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_BREAK = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_DELIMITER = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


@dataclass
class Block:
    kind: str  # heading | list_item | paragraph | table
    ref: str
    words: list[str]
    table: dict | None = None
    docling_level: int | None = None
    label: str = ""
    lines: tuple[int, int] | None = None


@dataclass
class TxtItem:
    kind: str
    start: int
    end: int
    text: str
    level: int
    line_range: tuple[int, int]
    ref: str | None = None
    cells: list[list[dict[str, Any]]] = field(default_factory=list)


def _words(text: str) -> list[str]:
    return [w.casefold() for w in WORD.findall(text or "")]


def docling_blocks(raw: dict) -> list[Block]:
    """Block-level items of a Markdown ``DoclingDocument.export_to_dict()``, in reading order."""
    lookup = {entry["self_ref"]: entry for collection in ("texts", "tables", "pictures", "groups")
              for entry in raw.get(collection, [])}
    blocks: list[Block] = []

    def text_of(ref: str) -> list[str]:
        node = lookup.get(ref) or {}
        words = _words(node.get("text", ""))
        for child in node.get("children", []):
            child_node = lookup.get(child["$ref"]) or {}
            if child_node.get("label") not in {"list", "ordered_list"}:
                words += text_of(child["$ref"])
        return words

    def walk(ref: str) -> None:
        node = lookup.get(ref)
        if node is None:
            return
        label = node.get("label", "")
        if ref.startswith("#/groups/"):
            if label == "inline":
                blocks.append(Block("paragraph", ref, text_of(ref), label=label))
                return
            for child in node.get("children", []):
                walk(child["$ref"])
            return
        if ref.startswith("#/pictures/"):
            return  # alt text stays in the exact paragraphs of its source line
        if ref.startswith("#/tables/"):
            cells = sorted((node.get("data") or {}).get("table_cells", []),
                           key=lambda c: (c.get("start_row_offset_idx", 0), c.get("start_col_offset_idx", 0)))
            words = [w for cell in cells for w in _words(cell.get("text", ""))]
            blocks.append(Block("table", ref, words, table=node.get("data") or {}, label=label))
            return
        kind = {"title": "heading", "section_header": "heading", "list_item": "list_item"}.get(label, "paragraph")
        level = 0 if label == "title" else node.get("level") if label == "section_header" else None
        blocks.append(Block(kind, ref, text_of(ref), docling_level=level, label=label))
        # Nested lists under a list item are blocks of their own, after their parent.
        for child in node.get("children", []):
            child_node = lookup.get(child["$ref"]) or {}
            if child_node.get("label") in {"list", "ordered_list"}:
                walk(child["$ref"])

    for child in (raw.get("body") or {}).get("children", []):
        walk(child["$ref"])
    return blocks


def _split_row(line: str) -> list[tuple[int, int]]:
    """Exact (start, end) offsets of the cells of one pipe-table line, relative to the line."""
    bounds: list[int] = [-1]
    escaped = False
    for index, char in enumerate(line):
        if char == "|" and not escaped:
            bounds.append(index)
        escaped = char == "\\" and not escaped
    bounds.append(len(line))
    cells = []
    for left, right in pairwise(bounds):
        start, end = left + 1, right
        while start < end and line[start].isspace():
            start += 1
        while end > start and line[end - 1].isspace():
            end -= 1
        cells.append((start, end))
    stripped = line.strip()
    if stripped.startswith("|"):
        cells = cells[1:]
    if stripped.endswith("|") and len(stripped) > 1:
        cells = cells[:-1]
    return cells


def _table_cells(text: str, starts: list[int], first: int, last: int,
                 data: dict) -> list[list[dict[str, Any]]] | None:
    """Docling's grid with the exact source cell texts; None when the source rows do not match it."""
    rows = []
    for line in range(first, last + 1):
        visible = text[starts[line]:starts[line + 1]].rstrip("\r\n")
        if not visible.strip() or _DELIMITER.match(visible):
            continue
        rows.append([(starts[line] + a, starts[line] + b) for a, b in _split_row(visible)])
    num_rows, num_cols = data.get("num_rows", 0), data.get("num_cols", 0)
    if len(rows) != num_rows or any(len(row) != num_cols for row in rows) or not num_cols:
        return None
    flags: dict[tuple[int, int], dict] = {}
    spans: dict[tuple[int, int], tuple[int, int]] = {}
    for cell in data.get("table_cells", []):
        key = (cell.get("start_row_offset_idx", 0), cell.get("start_col_offset_idx", 0))
        flags[key] = {name: True for name in TABLE_HEADER_FLAGS if cell.get(name)}
        spans[key] = (cell.get("row_span", 1), cell.get("col_span", 1))
    grid = []
    for r, row in enumerate(rows):
        mapped = []
        for c, (start, end) in enumerate(row):
            row_span, col_span = spans.get((r, c), (1, 1))
            cell = {"value": text[start:end], "row_span": row_span, "col_span": col_span}
            if end > start:
                cell["locator"] = {"kind": "text_span", "start": start, "end": end}
            if flags.get((r, c)):
                cell["source_attributes"] = flags[(r, c)]
            mapped.append(cell)
        grid.append(mapped)
    return grid


def align(text: str, raw: dict) -> list[TxtItem]:
    """Items with exact source spans: Docling structure where it aligns, exact paragraphs elsewhere."""
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    tokens = [(m.group().casefold(), m.start()) for m in WORD.finditer(text)]

    def line_of(offset: int) -> int:
        return bisect_right(starts, offset) - 1

    def visible(n: int) -> str:
        return text[starts[n]:starts[n + 1]].rstrip("\r\n")

    blocks = docling_blocks(raw)
    cursor = 0
    for block in blocks:
        matched = []
        for word in block.words:
            for j in range(cursor, min(cursor + WINDOW, len(tokens))):
                if tokens[j][0] == word:
                    matched.append(j)
                    cursor = j + 1
                    break
        if matched:
            block.lines = (line_of(tokens[matched[0]][1]), line_of(tokens[matched[-1]][1]))

    owner: dict[int, Block] = {}
    markup: set[int] = set()
    previous_last = -1
    items: list[TxtItem] = []
    for block in blocks:
        if block.lines is None:
            continue
        first, last = max(block.lines[0], previous_last + 1), block.lines[1]
        if block.kind == "heading":
            last = first
        if first > last:
            continue
        line = visible(first)
        offset = len(line) - len(line.lstrip())
        body = line[offset:]
        quote = _QUOTE.match(body)
        if quote:
            offset += quote.end()
            body = line[offset:]
        level = 1
        kind = block.kind
        if kind == "heading":
            atx = _ATX.match(body)
            if atx:
                level = len(atx.group(1))
                offset += atx.end()
            elif first + 1 < len(lines) and _SETEXT.match(visible(first + 1)):
                level = 1 if visible(first + 1).strip().startswith("=") else 2
                markup.add(first + 1)
            else:
                level = (block.docling_level or 0) + 1
        elif kind == "list_item":
            bullet = _BULLET.match(body)
            if bullet:
                offset += bullet.end()
        start = starts[first] + offset
        end = starts[last] + len(visible(last).rstrip())
        if end <= start:
            continue
        cells: list[list[dict[str, Any]]] = []
        if kind == "table":
            cells = _table_cells(text, starts, first, last, block.table or {}) or []
            if not cells:
                kind = "paragraph"
        for n in range(first, last + 1):
            owner[n] = block
        items.append(TxtItem(kind, start, end, text[start:end], level, (first + 1, last + 1),
                             ref=block.ref, cells=cells))
        previous_last = last

    # Every other non-blank source line is kept as an exact paragraph (old exact-spans behaviour);
    # only word-less Markdown markup is dropped: setext underlines, code fences, thematic breaks.
    run: list[int] = []

    def flush() -> None:
        if run:
            first, last = run[0], run[-1]
            line = visible(first)
            start = starts[first] + len(line) - len(line.lstrip())
            end = starts[last] + len(visible(last).rstrip())
            items.append(TxtItem("paragraph", start, end, text[start:end], 1, (first + 1, last + 1)))
            run.clear()

    for n in range(len(lines)):
        line = visible(n)
        if n in owner or not line.strip():
            flush()
            continue
        if n in markup or _FENCE.match(line) or _BREAK.match(line):
            flush()
            continue
        run.append(n)
    flush()
    items.sort(key=lambda item: item.start)
    return items
