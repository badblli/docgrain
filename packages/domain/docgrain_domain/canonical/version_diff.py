"""Pure file-version diff over DoclingDocument.export_to_dict() (WP124 / WP125).

Public contract: ``diff_docling_documents(before, after) -> DocumentChanges``.
Inputs are stored Docling JSON dictionaries, or DoclingDocument instances (exported
via export_to_dict); no parser, I/O, model, or docling dependency is required here.
The caller must pin/validate workspace, document and file-version scope.

``result.model_dump(mode="json")`` yields::

  has_changes: bool                 # False => nothing in the document's content changed
  added_units / removed_units / changed_units: int
  unchanged_units: int              # matched with equal text, moves included
  changes: [{
    operation: "added" | "removed" | "changed",
    kind: "heading" | "paragraph" | "list_item" | "table_cell" | "key_value" | "picture_text",
    address: {heading_path: [str], group_path: [str], position: int,
              # table_cell: table, row_header, column_header; key_value: key
              },
    before: str | None, after: str | None,           # raw Docling text, null on the missing side
    before_locator / after_locator: {ref, provenance, row?, column?, cell_ref?, cell_id?} | None,
  }]

Address = where the unit is in the structure (the side it is reported on: the new side
for added/changed, the old side for removed). ``position`` is the unit's ordinal among
same-kind units under the same heading/group path; it only orders, it is not identity.
Locators carry the Docling ``ref`` (``#/texts/3``, ``#/groups/0`` for a formatted
paragraph, ``#/tables/0`` + zero-based row/column for a cell, graph ``cell_id`` for a
key-value) and Docling ``provenance`` (page_no/bbox with coord_origin). Refs are
version-local, NOT stable identities across versions.

Units: headings (title/section_header), paragraphs (text items; an InlineGroup of
formatted runs is one paragraph; table captions are paragraphs), list items, table
cells addressed by row + column header labels (Docling flags; otherwise the first
column/row text, else "Satır n"/"Sütun n"), key-value items (graph links and field
areas), picture text (annotations, captions, text inside pictures). Furniture
(page headers/footers) is ignored.

Matching, in order: equal normalized text at the same structure address; equal prose
anywhere (a moved, unchanged block is not a change; cells/keys never trade values
across addresses); renamed headings (outermost first, ratio >= .50) so their sections
keep matching; best similarity at the same address (cells/keys: always, the address is
their identity; prose: ratio >= .60); prose across addresses (>= .78); finally table
cells by grid slot (table ordinal under the heading path, row, column), so an edited
row/column label or caption is one changed cell, not a removed + added row. Anything
left is removed/added. Text is compared after NFKC + whitespace collapsing only, so
re-saved files, non-breaking spaces and composed/decomposed letters are not changes.
Duplicates keep their multiplicity. Fuzzy passes skip pairs that share too few words;
when more than 250 000 pairs would be scored (a rewritten long document), only units at
a similar relative place (within 5 %) are compared. Geometry, file bytes and approval
state are out of scope.

WP125 can skip a document iff ``has_changes`` is false; otherwise the units (and
locators on both sides) in ``changes`` are what changed.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict, deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal

from pydantic import BaseModel, Field

_KINDS = frozenset({"heading", "paragraph", "list_item", "table_cell", "key_value", "picture_text"})
# Units whose address is their identity: equal values never move between addresses.
_STRONG = frozenset({"table_cell", "key_value"})


class UnitChange(BaseModel):
    operation: Literal["added", "removed", "changed"]
    kind: Literal["heading", "paragraph", "list_item", "table_cell", "key_value", "picture_text"]
    address: dict[str, Any]
    before: str | None = None
    after: str | None = None
    before_locator: dict[str, Any] | None = None
    after_locator: dict[str, Any] | None = None


class DocumentChanges(BaseModel):
    has_changes: bool = False
    added_units: int = 0
    removed_units: int = 0
    changed_units: int = 0
    unchanged_units: int = 0
    changes: list[UnitChange] = Field(default_factory=list)


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


@dataclass
class _Unit:
    kind: str
    address: dict
    text: str
    locator: dict
    # Table cells only: (table ordinal under its heading path, row, column). A fallback for
    # renamed row/column labels or captions; never identity.
    slot: tuple | None = None

    @property
    def key(self) -> tuple:
        # Position is only a disambiguator within a structure address, not identity.
        return (self.kind, tuple(_norm(h) for h in self.address.get("heading_path", [])),
                tuple(_norm(g) for g in self.address.get("group_path", [])),
                *(_norm(str(self.address.get(k, "")))
                  for k in ("table", "row_header", "column_header", "key")))


class _Reader:
    def __init__(self, document):
        self.doc = document if isinstance(document, dict) else document.export_to_dict()
        if not isinstance(self.doc, dict) or not isinstance(self.doc.get("body"), dict):
            raise TypeError("a DoclingDocument with a body is required")
        self.units: list[_Unit] = []
        self.seen: set[str] = set()
        self.headings: list[tuple[int, str]] = []
        self.groups: list[str] = []
        self.picture_depth = 0
        self.positions: dict[tuple, int] = defaultdict(int)

    def resolve(self, value) -> dict:
        if not isinstance(value, dict):
            return {}
        if "$ref" not in value:
            return value
        result = self.doc
        try:
            for part in value["$ref"].removeprefix("#/").split("/"):
                result = result[int(part)] if isinstance(result, list) else result[part]
        except (KeyError, IndexError, ValueError, TypeError):
            return {}
        return result if isinstance(result, dict) else {}

    def text(self, item: dict) -> str:
        text = item.get("text")
        if text is not None:
            return str(text)
        # RichTableCell references Docling text items instead of duplicating text.
        return " ".join(self.text(self.resolve(ref)) for ref in item.get("refs", []))

    def inline_text(self, item: dict) -> str:
        """Own text plus InlineGroup runs: Docling splits a formatted paragraph into runs."""
        parts = [self.text(item)] if item.get("text") is not None or item.get("refs") else []
        for ref in item.get("children") or []:
            child = self.resolve(ref)
            if child.get("label") == "inline" or (
                    item.get("label") == "inline" and child.get("label") not in {"list", "ordered_list"}):
                self.seen.add(child.get("self_ref", ""))
                parts.append(self.inline_text(child))
        return " ".join(part for part in parts if part)

    def inline_prov(self, item: dict) -> list:
        prov = item.get("prov") or []
        prov = [prov] if isinstance(prov, dict) else list(prov)
        for ref in item.get("children") or []:
            child = self.resolve(ref)
            if child.get("label") == "inline" or (
                    item.get("label") == "inline" and child.get("label") not in {"list", "ordered_list"}):
                prov += self.inline_prov(child)
        return prov

    def locator(self, item, **extra):
        prov = item.get("prov") or []
        return {"ref": item.get("self_ref"),
                "provenance": [prov] if isinstance(prov, dict) else prov, **extra}

    def add(self, kind, text, item, *, locator=None, slot=None, **address):
        # Empty cells still matter: empty -> value is one changed cell.
        if not _norm(text) and kind not in {"table_cell", "key_value"}:
            return
        scope = (kind, tuple(self.headings), tuple(self.groups))
        position = self.positions[scope]
        self.positions[scope] += 1
        self.units.append(_Unit(kind, {"heading_path": [h for _, h in self.headings],
                                      "group_path": list(self.groups), "position": position,
                                      **address}, text, locator or self.locator(item), slot))

    def children(self, item):
        for child in item.get("children") or []:
            self.walk(self.resolve(child))

    def walk(self, item):
        ref = item.get("self_ref")
        if ref and ref in self.seen:
            return
        if ref:
            self.seen.add(ref)
        if item.get("content_layer", "body") != "body":
            return
        label = item.get("label", "")
        collection = (ref or "").split("/")[1:2]
        if collection == ["tables"] or label == "table":
            self.table(item)
            return
        if collection in (["key_value_items"], ["form_items"]):
            self.graph(item)
            return
        if collection == ["field_regions"] or label in {"key_value_area", "form_area"}:
            self.area(item)
            return
        if collection == ["pictures"] or label == "picture":
            texts = [self.text(item)]
            texts += [str(a.get("text", "")) for a in item.get("annotations") or []]
            texts += [self.text(self.resolve(c)) for c in item.get("captions") or []]
            self.add("picture_text", "\n".join(t for t in texts if t), item)
            for caption in item.get("captions") or []:
                self.seen.add(caption.get("$ref", ""))
            self.picture_depth += 1
            self.children(item)
            self.picture_depth -= 1
            return
        if label == "inline":
            # One formatted paragraph = one unit, not one unit per bold/italic run.
            self.add("picture_text" if self.picture_depth else "paragraph", self.inline_text(item),
                     {**item, "prov": self.inline_prov(item)})
            return
        if label in {"title", "section_header"}:
            level = 0 if label == "title" else int(item.get("level") or 1)
            self.headings = [(n, t) for n, t in self.headings if n < level]
            text = self.inline_text(item)
            self.add("heading", text, {**item, "prov": self.inline_prov(item)})
            self.headings.append((level, text))
        elif collection == ["texts"] or label in {"text", "paragraph", "list_item"}:
            kind = "key_value" if label in {"field_key", "field_value"} else (
                "list_item" if label == "list_item" else "paragraph")
            if self.picture_depth:
                kind = "picture_text"
            self.add(kind, self.inline_text(item), {**item, "prov": self.inline_prov(item)})
        # Named sheets/areas/groups supply useful structure without inventing headings.
        name = item.get("name")
        named = name and name not in {"_root_", "group", "list", "ordered list", "unordered list"}
        if named:
            self.groups.append(str(name))
        if label == "sheet":
            outer = self.headings
            self.headings = []
            self.children(item)
            self.headings = outer
        else:
            self.children(item)
        if named:
            self.groups.pop()

    def table(self, item):
        captions = [self.text(self.resolve(c)) for c in item.get("captions") or []]
        name = next((c for c in captions if c), None) or item.get("name") or (
            self.headings[-1][1] if self.headings else "Tablo")
        for caption in item.get("captions") or []:
            self.seen.add(caption.get("$ref", ""))
            # An edited caption is its own change; cells still pair through their slot.
            self.add("paragraph", self.text(self.resolve(caption)), self.resolve(caption))
        ordinal = self.positions[("table", tuple(self.headings))]
        self.positions[("table", tuple(self.headings))] += 1
        data = item.get("data") or {}
        cells = data.get("table_cells") or []
        # Serialized TableData.grid may be supplied without the flat list.
        if not cells:
            seen = set()
            for row in data.get("grid") or []:
                for cell in row:
                    if not cell:
                        continue
                    key = (cell.get("start_row_offset_idx"), cell.get("start_col_offset_idx"))
                    if key not in seen:
                        cells.append(cell)
                        seen.add(key)

        def start(cell, axis):
            return int(cell.get(f"start_{axis}_offset_idx", 0))

        def span(cell, axis):
            return range(start(cell, axis), max(int(cell.get(f"end_{axis}_offset_idx", 0)), start(cell, axis) + 1))

        # Header labels per row/column index, built once (sheets can have many cells).
        column_labels, row_labels = defaultdict(list), defaultdict(list)
        first_in_row, first_in_column = {}, {}
        for cell in cells:
            for col in span(cell, "col"):
                if cell.get("column_header"):
                    column_labels[col].append(self.text(cell))
                if start(cell, "row") == 0:
                    first_in_column.setdefault(col, cell)
            for row in span(cell, "row"):
                if cell.get("row_header"):
                    row_labels[row].append(self.text(cell))
                if start(cell, "col") == 0:
                    first_in_row.setdefault(row, cell)
        for cell in cells:
            row, col = start(cell, "row"), start(cell, "col")
            columns, rows = list(column_labels.get(col, [])), list(row_labels.get(row, []))
            # Docling often supplies only column flags. First body cell is the row label.
            if not rows and not cell.get("column_header") and row in first_in_row:
                rows = [self.text(first_in_row[row])]
            # A table without any header flag: its first row labels the columns.
            if not columns and not column_labels and row > 0 and col in first_in_column:
                columns = [self.text(first_in_column[col])]
            prov = cell.get("prov") or item.get("prov") or []
            prov = [prov] if isinstance(prov, dict) else prov
            if cell.get("bbox") and prov:
                prov = [{**prov[0], "bbox": cell["bbox"]}]
            holder = {**item, "prov": prov}
            self.add("table_cell", self.text(cell), item,
                     locator=self.locator(holder, row=row, column=col, cell_ref=cell.get("ref")),
                     slot=(ordinal, row, col),
                     table=str(name), row_header=" / ".join(rows) or f"Satır {row + 1}",
                     column_header=" / ".join(columns) or f"Sütun {col + 1}")

    def graph(self, item):
        graph = item.get("graph") or {}
        cells = {c.get("cell_id"): c for c in graph.get("cells") or []}
        linked = set()
        for link in graph.get("links") or []:
            key, value = cells.get(link.get("source_cell_id")), cells.get(link.get("target_cell_id"))
            if link.get("label") == "to_key":
                key, value = value, key
            if not key or not value or key.get("label") != "key" or value.get("label") not in {"value", "checkbox"}:
                continue
            linked.add(key.get("cell_id"))
            holder = {**item, "prov": value.get("prov") or item.get("prov")}
            self.add("key_value", self.text(value), item, key=self.text(key),
                     locator=self.locator(holder, cell_id=value.get("cell_id")))
        for key in cells.values():
            if key.get("label") == "key" and key.get("cell_id") not in linked:
                self.add("key_value", self.text(key), item, key=self.text(key))

    def area(self, item):
        key = None
        for ref in item.get("children") or []:
            child = self.resolve(ref)
            label = child.get("label")
            if label == "field_key":
                key = child
                self.seen.add(child.get("self_ref", ""))
            elif label == "field_value" and key is not None:
                self.add("key_value", self.text(child), child, key=self.text(key))
                self.seen.add(child.get("self_ref", ""))
                key = None
            elif child.get("children"):
                self.area(child)
            else:
                self.walk(child)
        if key is not None:
            self.add("key_value", "", key, key=self.text(key))


def diff_docling_documents(before, after) -> DocumentChanges:
    """Return deterministic content changes; see module docstring for WP125 contract."""
    left, right = _Reader(before), _Reader(after)
    left.walk(left.doc["body"])
    right.walk(right.doc["body"])
    old, new = left.units, right.units
    remaining_old, remaining_new = set(range(len(old))), set(range(len(new)))
    unchanged = 0
    changes: list[UnitChange] = []
    heading_moves: dict[tuple, tuple] = {}

    def old_key(unit):
        key = list(unit.key)
        path = key[1]
        for source in sorted(heading_moves, key=len, reverse=True):
            if path[:len(source)] == source:
                key[1] = heading_moves[source] + path[len(source):]
                # A table named by its enclosing heading follows that rename.
                if unit.kind == "table_cell" and key[3] == source[-1]:
                    key[3] = heading_moves[source][-1]
                break
        return tuple(key)

    def pair(i, j):
        nonlocal unchanged
        a, b = old[i], new[j]
        remaining_old.remove(i)
        remaining_new.remove(j)
        if _norm(a.text) == _norm(b.text):
            unchanged += 1
        else:
            if a.kind == "heading":
                heading_moves[(*a.key[1], _norm(a.text))] = (*b.key[1], _norm(b.text))
            changes.append(UnitChange(operation="changed", kind=b.kind, address=b.address,
                                      before=a.text, after=b.text,
                                      before_locator=a.locator, after_locator=b.locator))

    # Exact equality at structure addresses first; preserve duplicate multiplicity.
    exact = defaultdict(deque)
    for j, unit in enumerate(new):
        exact[(unit.key, _norm(unit.text))].append(j)
    for i, unit in enumerate(old):
        matches = exact[(unit.key, _norm(unit.text))]
        if matches:
            pair(i, matches.popleft())
    # Equal moved prose/headings/picture text. Cells/keys cannot exchange equal values
    # across different addresses: a price swap must still be visible.
    buckets = defaultdict(deque)
    for j in sorted(remaining_new):
        buckets[(new[j].kind, _norm(new[j].text))].append(j)
    for i in sorted(remaining_old):
        a = old[i]
        if a.kind in _STRONG:
            continue
        matches = buckets[(a.kind, _norm(a.text))]
        if matches:
            pair(i, matches.popleft())
    old_norm, new_norm = [_norm(u.text) for u in old], [_norm(u.text) for u in new]
    old_words = [frozenset(text.casefold().split()) for text in old_norm]
    new_words = [frozenset(text.casefold().split()) for text in new_norm]

    def scored(old_ids, new_ids, floor):
        """(-score, position distance, i, j) for pairs reaching ``floor``.

        One matcher per new unit caches its text; length, shared-word and character-count
        bounds skip hopeless pairs before the full ratio. Very large groups (a rewritten
        long document) only compare units at a similar relative place in the document.
        """
        result = []
        window = .05 if len(old_ids) * len(new_ids) > 250_000 else None
        for j in new_ids:
            b, b_words = new_norm[j], new_words[j]
            matcher = SequenceMatcher(None, "", b, autojunk=False)
            for i in old_ids:
                a, a_words = old_norm[i], old_words[i]
                total = len(a) + len(b)
                if total and 2 * min(len(a), len(b)) / total < floor:
                    continue
                if window is not None and abs(i / len(old) - j / len(new)) > window:
                    continue
                # Similar prose shares words; unrelated sentences share only a few stop words.
                if (floor and min(len(a_words), len(b_words)) >= 3
                        and 4 * len(a_words & b_words) < floor * (len(a_words) + len(b_words))):
                    continue
                matcher.set_seq1(a)
                if total and matcher.quick_ratio() < floor:
                    continue
                score = matcher.ratio() if total else 1.0
                if score >= floor:
                    result.append((-score, abs(old[i].address["position"] - new[j].address["position"]), i, j))
        return result

    def grouped(kinds, key_of_old, key_of_new, depth=None):
        groups = defaultdict(lambda: ([], []))
        for i in sorted(remaining_old):
            if old[i].kind in kinds and (depth is None or len(old[i].key[1]) == depth):
                groups[key_of_old(old[i])][0].append(i)
        for j in sorted(remaining_new):
            if new[j].kind in kinds:
                groups[key_of_new(new[j])][1].append(j)
        return [ids for ids in groups.values() if ids[0] and ids[1]]

    def pair_best(candidates):
        for _, _, i, j in sorted(candidates):
            if i in remaining_old and j in remaining_new:
                pair(i, j)

    # Resolve renamed headings before their children, outermost first, so a title edit
    # does not turn changes inside that section into additions/removals.
    for depth in sorted({len(old[i].key[1]) for i in remaining_old if old[i].kind == "heading"}):
        pair_best([c for olds, news in grouped({"heading"}, old_key, lambda u: u.key, depth)
                   for c in scored(olds, news, .50)])
    # Best similarity wins inside an address (any score for cells/keys: the address is
    # their identity), then across addresses for prose only.
    candidates = []
    for olds, news in grouped(_KINDS, old_key, lambda u: u.key):
        candidates += scored(olds, news, 0.0 if old[olds[0]].kind in _STRONG else .60)
    pair_best(candidates)
    pair_best([c for olds, news in grouped(_KINDS - _STRONG, lambda u: u.kind, lambda u: u.kind)
               for c in scored(olds, news, .78)])
    # Cells whose row/column label or table caption was edited keep their grid slot
    # under the same (renamed) heading: "Delivery" -> "Shipping" is one changed cell.
    slots = defaultdict(deque)
    for j in sorted(remaining_new):
        if new[j].slot is not None:
            slots[(new[j].key[1], new[j].slot)].append(j)
    for i in sorted(remaining_old):
        if old[i].slot is not None:
            matches = slots[(old_key(old[i])[1], old[i].slot)]
            if matches:
                pair(i, matches.popleft())
    for i in sorted(remaining_old):
        a = old[i]
        changes.append(UnitChange(operation="removed", kind=a.kind, address=a.address,
                                  before=a.text, before_locator=a.locator))
    for j in sorted(remaining_new):
        b = new[j]
        changes.append(UnitChange(operation="added", kind=b.kind, address=b.address,
                                  after=b.text, after_locator=b.locator))
    return DocumentChanges(has_changes=bool(changes), changes=changes, unchanged_units=unchanged,
                           added_units=sum(c.operation == "added" for c in changes),
                           removed_units=sum(c.operation == "removed" for c in changes),
                           changed_units=sum(c.operation == "changed" for c in changes))
