"""Structural units from a stored DoclingDocument (WP117, decision 21). Read-only, no model.

Input is the per-version Docling artifact the worker keeps: ``DoclingDocument.export_to_dict()``
written by ``structural.py`` (``legacy_json``), stored under
``artifacts/{document_id}/{version_id}/structural/docling/{sha256}.json`` and referenced from the
canonical snapshot as the artifact with role ``docling-document`` (PDFs also have the same JSON as
``artifacts/{document_id}/{version_id}/document.json``). docling-core is not installed on the host,
so this module reads the JSON as plain dicts; a ``DoclingDocument`` object is accepted too and
exported first.

A *unit* is one structure Docling already returns:

* ``table``  header row(s) -> field names, rows -> items, row-header (else first) column -> item name;
* ``list``   list group -> items, heading above (or the group name) -> unit name;
* ``key_value`` key-value / form graph, field region or key-value area -> fields (keys) and one item;
* ``sheet``  spreadsheet sheet -> name, its table units as ``children``.

Every item name and value keeps its evidence (item ``self_ref``, row/column for cells, page, box).
``group_units`` then joins units of one workspace into candidate collections and items with the same
normalized name into candidate records. Pure functions: no network, no model, no writes.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any

from .normalize import fold, format_key

# Names Docling gives groups by default; they carry no meaning.
_DEFAULT_GROUP_NAMES = {"", "group", "list", "ordered list", "unordered list", "key-value area",
                        "form area", "_root_"}
_UNIT_KINDS = ("table", "list", "key_value", "sheet")
# Candidate-name sources, strongest first.
NAME_SOURCES = ("caption", "heading", "sheet", "group_name", "list_parent", "preceding_text",
                "name_field", "none")
FIELD_JACCARD = 0.6
WEAK_FIELD_JACCARD = 0.3
ITEM_OVERLAP = 0.5
WEAK_ITEM_OVERLAP = 0.25
_SHORT_TEXT = 80


@dataclass(frozen=True)
class Evidence:
    document_id: str
    ref: str
    text: str
    page_no: int | None = None
    bbox: dict | None = None
    row: int | None = None
    col: int | None = None
    charspan: list[int] | None = None


@dataclass
class UnitItem:
    name: str | None
    name_evidence: Evidence | None = None
    values: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    section: str | None = None


@dataclass
class StructureUnit:
    id: str
    kind: str
    document_id: str
    ref: str
    name: str | None
    name_source: str
    fields: list[str] = field(default_factory=list)
    name_field: str | None = None
    header_source: str | None = None
    items: list[UnitItem] = field(default_factory=list)
    heading_path: list[str] = field(default_factory=list)
    sheet: str | None = None
    children: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def norm(text: str | None) -> str:
    """Comparison key for names and field labels (case, Turkish letters, accents, punctuation)."""
    if not text:
        return ""
    return fold(str(text)).strip()


def _value_key(text: str) -> str:
    return format_key(text)


# --------------------------------------------------------------------------- reading the JSON


def _core_document(document: Any):
    """The docling-core ``DoclingDocument`` when docling-core is installed (worker image), else None."""
    if hasattr(document, "iterate_items"):
        return document
    try:
        from docling_core.types.doc import DoclingDocument
    except ImportError:  # host venv: read the same JSON as plain dicts
        return None
    try:
        return DoclingDocument.model_validate(document)
    except ValueError:
        return None


class _Doc:
    def __init__(self, document: Any, document_id: str, *, use_docling_core: bool = True):
        self.core = _core_document(document) if use_docling_core else None
        if hasattr(document, "export_to_dict"):
            document = document.export_to_dict()
        self.raw: dict = document
        self.document_id = document_id

    def core_table(self, ref: str):
        if self.core is None or not ref.startswith("#/tables/"):
            return None
        try:
            return self.core.tables[int(ref.rsplit("/", 1)[1])]
        except (IndexError, ValueError):
            return None

    def resolve(self, ref: str) -> dict | None:
        parts = ref.lstrip("#/").split("/")
        node: Any = self.raw
        try:
            for part in parts:
                node = node[int(part)] if isinstance(node, list) else node[part]
        except (KeyError, IndexError, ValueError, TypeError):
            return None
        return node if isinstance(node, dict) else None

    def prov(self, item: dict) -> tuple[int | None, dict | None, list[int] | None]:
        provs = item.get("prov") or []
        if not provs:
            return None, None, None
        first = provs[0]
        return first.get("page_no"), first.get("bbox"), first.get("charspan")

    def evidence(self, item: dict, text: str, **extra) -> Evidence:
        page, bbox, charspan = self.prov(item)
        return Evidence(document_id=self.document_id, ref=item.get("self_ref", ""), text=text,
                        page_no=page, bbox=extra.pop("bbox", None) or bbox,
                        charspan=list(charspan) if charspan else None, **extra)


def _text(item: dict | None) -> str:
    if not item:
        return ""
    return " ".join(str(item.get("text") or item.get("orig") or "").split())


def _is_body(item: dict) -> bool:
    return item.get("content_layer", "body") == "body"


def _numeric(text: str) -> bool:
    return bool(re.fullmatch(r"[\d\s.,:/%+\-–]*", text))


class _Walker:
    def __init__(self, doc: _Doc):
        self.doc = doc
        self.units: list[StructureUnit] = []
        self.headings: list[tuple[int, str]] = []
        self.preceding: str | None = None
        self.sheet: str | None = None
        self.visited: set[str] = set()

    # context ---------------------------------------------------------------
    def _context(self) -> tuple[str | None, str]:
        if self.sheet:
            return self.sheet, "sheet"
        if self.headings:
            return self.headings[-1][1], "heading"
        if self.preceding:
            return self.preceding, "preceding_text"
        return None, "none"

    def _path(self) -> list[str]:
        return ([self.sheet] if self.sheet else []) + [text for _, text in self.headings]

    def _unit(self, kind: str, item: dict, name: str | None, source: str, **kwargs) -> StructureUnit:
        ref = item.get("self_ref", "")
        unit = StructureUnit(id=f"{self.doc.document_id}{ref}", kind=kind,
                             document_id=self.doc.document_id, ref=ref, name=name,
                             name_source=source if name else "none", heading_path=self._path(),
                             sheet=self.sheet, **kwargs)
        self.units.append(unit)
        return unit

    # traversal -------------------------------------------------------------
    def walk(self, ref: str) -> None:
        if ref in self.visited:
            return
        item = self.doc.resolve(ref)
        if item is None or not _is_body(item):
            return
        self.visited.add(ref)
        collection = ref.lstrip("#/").split("/")[0]
        label = item.get("label", "")
        if collection == "texts":
            self._text(item, label)
        elif collection == "tables":
            self._table(item)
        elif collection in {"key_value_items", "form_items"}:
            self._graph(item)
        elif collection == "field_regions":
            self._field_region(item)
        elif collection in {"groups", "body"}:
            self._group(item, label)

    def _children(self, item: dict) -> None:
        for child in item.get("children") or []:
            self.walk(child.get("$ref", ""))

    def _text(self, item: dict, label: str) -> None:
        text = _text(item)
        if label in {"title", "section_header"} and text:
            level = 0 if label == "title" else int(item.get("level") or 1)
            self.headings = [(lvl, t) for lvl, t in self.headings if lvl < level] + [(level, text)]
            self.preceding = None
        elif label in {"text", "paragraph", "caption"} and text:
            short = len(text) <= _SHORT_TEXT and not text.endswith((".", "!", "?"))
            self.preceding = text if short else None
        self._children(item)

    def _group(self, item: dict, label: str) -> None:
        name = str(item.get("name") or "").strip()
        if label == "sheet":
            outer = self.sheet
            self.sheet = name or "sheet"
            unit = self._unit("sheet", item, self.sheet, "sheet")
            start = len(self.units)
            self._children(item)
            unit.children = [u.id for u in self.units[start:] if u.kind != "sheet"]
            self.sheet = outer
        elif label in {"list", "ordered_list"}:
            self._list(item, name)
        elif label in {"key_value_area", "form_area"}:
            self._area(item, name)
        else:
            self._children(item)

    def _list(self, group: dict, name: str, parent_text: str | None = None) -> None:
        if name.casefold() not in _DEFAULT_GROUP_NAMES:
            unit_name, source = name, "group_name"
        elif parent_text:
            unit_name, source = parent_text, "list_parent"
        else:
            unit_name, source = self._context()
        unit = self._unit("list", group, unit_name, source)
        nested: list[tuple[dict, str]] = []
        for child in group.get("children") or []:
            ref = child.get("$ref", "")
            entry = self.doc.resolve(ref)
            if entry is None or not _is_body(entry):
                continue
            self.visited.add(ref)
            text = _text(entry)
            if ref.startswith("#/texts/") and text:
                unit.items.append(self._list_item(entry, text))
            for grandchild in entry.get("children") or []:
                sub = self.doc.resolve(grandchild.get("$ref", ""))
                if sub and sub.get("label") in {"list", "ordered_list"}:
                    nested.append((sub, text))
            if entry.get("label") in {"list", "ordered_list"} and not ref.startswith("#/texts/"):
                nested.append((entry, ""))
        for sub, text in nested:
            if sub.get("self_ref") not in self.visited:
                self.visited.add(sub.get("self_ref", ""))
                self._list(sub, str(sub.get("name") or ""), text or None)

    def _list_item(self, entry: dict, text: str) -> UnitItem:
        evidence = self.doc.evidence(entry, text)
        head, sep, tail = text.partition(":")
        if sep and head.strip() and tail.strip() and len(head) <= 40 and not _numeric(head):
            return UnitItem(name=head.strip(), name_evidence=evidence,
                            values={"detail": tail.strip()}, evidence={"detail": evidence})
        return UnitItem(name=text, name_evidence=evidence)

    def _area(self, group: dict, name: str) -> None:
        pairs: list[tuple[str, str, dict]] = []
        key: tuple[str, dict] | None = None
        for child in group.get("children") or []:
            ref = child.get("$ref", "")
            entry = self.doc.resolve(ref)
            if entry is None or not ref.startswith("#/texts/"):
                continue
            self.visited.add(ref)
            text, label = _text(entry), entry.get("label")
            if label == "field_key":
                key = (text, entry)
            elif label == "field_value" and key:
                pairs.append((key[0], text, entry))
                key = None
            else:
                head, sep, tail = text.partition(":")
                if sep and head.strip() and tail.strip():
                    pairs.append((head.strip(), tail.strip(), entry))
        if pairs:
            unit_name, source = ((name, "group_name") if name.casefold() not in
                                 _DEFAULT_GROUP_NAMES else self._context())
            unit = self._unit("key_value", group, unit_name, source)
            self._fill_key_values(unit, [(k, v, self.doc.evidence(e, v)) for k, v, e in pairs])
        # Key-value items, tables or field regions inside the area are units of their own.
        self._children(group)

    def _fill_key_values(self, unit: StructureUnit, pairs: list[tuple[str, str, Evidence]]) -> None:
        item = UnitItem(name=None)
        for key, value, evidence in pairs:
            label = _unique(key, unit.fields)
            unit.fields.append(label)
            if value:
                item.values[label] = value
                item.evidence[label] = evidence
        unit.items.append(item)

    def _graph(self, item: dict) -> None:
        graph = item.get("graph") or {}
        cells = {cell.get("cell_id"): cell for cell in graph.get("cells") or []}
        pairs: list[tuple[str, str, Evidence]] = []
        linked: set = set()
        for link in graph.get("links") or []:
            source, target = cells.get(link.get("source_cell_id")), cells.get(link.get("target_cell_id"))
            if not source or not target:
                continue
            if link.get("label") == "to_key":
                source, target = target, source
            elif link.get("label") not in {"to_value", "unspecified", None}:
                continue
            if source.get("label") == "key" and target.get("label") in {"value", "checkbox"}:
                pairs.append((_text(source), _text(target), self._cell_evidence(item, target)))
                linked.update({source.get("cell_id"), target.get("cell_id")})
        for cell_id, cell in cells.items():
            if cell.get("label") == "key" and cell_id not in linked:
                pairs.append((_text(cell), "", self._cell_evidence(item, cell)))
        if pairs:
            name, source = self._context()
            unit = self._unit("key_value", item, name, source)
            self._fill_key_values(unit, pairs)

    def _cell_evidence(self, item: dict, cell: dict) -> Evidence:
        provs = cell.get("prov")
        if isinstance(provs, dict):
            provs = [provs]
        holder = {"self_ref": item.get("self_ref", ""), "prov": provs or item.get("prov")}
        return self.doc.evidence(holder, _text(cell))

    def _field_region(self, region: dict) -> None:
        pairs: list[tuple[str, str, Evidence]] = []
        heading = None
        for child in region.get("children") or []:
            entry = self.doc.resolve(child.get("$ref", ""))
            if entry is None:
                continue
            self.visited.add(child.get("$ref", ""))
            key = value = None
            for part in [entry] + [self.doc.resolve(c.get("$ref", "")) or {}
                                   for c in entry.get("children") or []]:
                label = part.get("label")
                if label == "field_heading":
                    heading = heading or _text(part)
                elif label == "field_key":
                    key = part
                elif label == "field_value":
                    value = part
            if key is not None:
                text = _text(value) if value else ""
                pairs.append((_text(key), text, self.doc.evidence(value or key, text)))
        if pairs:
            name, source = (heading, "heading") if heading else self._context()
            unit = self._unit("key_value", region, name, source)
            self._fill_key_values(unit, pairs)

    def _table(self, item: dict) -> None:
        captions = [_text(self.doc.resolve(ref.get("$ref", ""))) for ref in item.get("captions") or []]
        caption = next((c for c in captions if c), None)
        name, source = (caption, "caption") if caption else self._context()
        unit = self._unit("table", item, name, source)
        _read_table(self.doc, item, unit)
        if unit.name is None and unit.name_field:
            unit.name, unit.name_source = unit.name_field, "name_field"


def _unique(label: str, existing: list[str]) -> str:
    label = label or f"col_{len(existing) + 1}"
    if label not in existing:
        return label
    index = 2
    while f"{label} ({index})" in existing:
        index += 1
    return f"{label} ({index})"


def _dict_grid(data: dict, rows: int, cols: int) -> list[list[dict | None]]:
    """``TableData.grid`` as stored in the JSON; rebuilt from ``table_cells`` and spans if absent."""
    stored = data.get("grid")
    if stored and len(stored) == rows and all(len(row) == cols for row in stored):
        return stored
    grid: list[list[dict | None]] = [[None] * cols for _ in range(rows)]
    for cell in data.get("table_cells") or []:
        for r in range(cell.get("start_row_offset_idx", 0), min(cell.get("end_row_offset_idx", 0), rows)):
            for c in range(cell.get("start_col_offset_idx", 0), min(cell.get("end_col_offset_idx", 0), cols)):
                grid[r][c] = cell
    return grid


def _header_rows(grid: list[list[dict | None]]) -> int:
    """Leading rows with a column-header cell starting in that row (Docling's dataframe rule)."""
    count = 0
    for r, row in enumerate(grid):
        if any(cell and cell.get("column_header") and cell.get("start_row_offset_idx") == r
               for cell in row):
            count += 1
        else:
            break
    return count


def _table_view(doc: _Doc, item: dict) -> tuple[list[list[dict | None]], list[list[str]], int]:
    """Cell grid (dicts), cell texts and the number of header rows.

    With docling-core installed: ``TableItem.data.grid`` and ``TableItem.export_to_dataframe(doc)``
    (header rows = grid rows minus dataframe rows). Texts are the plain ``TableCell.text``: for DOCX
    rich cells the dataframe returns Markdown (``**bold**``), which would not match values. On the
    host the stored JSON (the model dump of that ``TableData``, including its ``grid``) is read with
    the same rule.
    """
    table = doc.core_table(item.get("self_ref", ""))
    if table is not None:
        grid_items = table.data.grid
        headers = len(grid_items) - len(table.export_to_dataframe(doc=doc.core))
        grid = [[cell.model_dump(mode="json") for cell in row] for row in grid_items]
        return grid, [[_text(cell) for cell in row] for row in grid], headers
    data = item.get("data") or {}
    grid = _dict_grid(data, int(data.get("num_rows") or 0), int(data.get("num_cols") or 0))
    return grid, [[_text(cell) for cell in row] for row in grid], _header_rows(grid)


def _read_table(doc: _Doc, item: dict, unit: StructureUnit) -> None:
    data = item.get("data") or {}
    rows, cols = int(data.get("num_rows") or 0), int(data.get("num_cols") or 0)
    if not data.get("table_cells") or not rows or not cols:
        return
    grid, texts, headers = _table_view(doc, item)

    def text(r: int, c: int) -> str:
        return texts[r][c]

    def filled(r: int) -> list[int]:
        return [c for c in range(cols) if text(r, c)]

    header_rows = list(range(headers))
    unit.header_source = "column_header" if header_rows else None
    if not header_rows and rows >= 2:
        # Our fallback (Docling's dataframe would number the columns): a distinct, non-numeric
        # first row names the fields.
        first = [text(0, c) for c in range(cols)]
        if all(first) and not any(_numeric(value) for value in first) and len(set(first)) == cols:
            header_rows, unit.header_source = [0], "first_row"
    unit.header_source = unit.header_source or "none"
    labels: list[str] = []
    for c in range(cols):
        parts: list[str] = []
        for r in header_rows:
            value = text(r, c)
            if value and value not in parts:
                parts.append(value)
        labels.append(_unique(" / ".join(parts), labels))
    unit.fields = labels

    data_rows = [r for r in range(rows) if r not in header_rows]
    flagged = sorted({c for r in data_rows for c in range(cols)
                      if grid[r][c] and grid[r][c].get("row_header") and text(r, c)})
    name_col = flagged[0] if flagged else 0
    if not flagged:
        values = [text(r, 0) for r in data_rows if text(r, 0)]
        if values and all(_numeric(v) for v in values) and cols > 1:
            name_col = 1
    unit.name_field = labels[name_col]
    section = None
    for r in data_rows:
        present = filled(r)
        if not present:
            continue
        only = grid[r][present[0]] or {}
        starts = {(grid[r][c] or {}).get("start_col_offset_idx") for c in present}
        full_width = (len(starts) == 1 and cols > 1 and only.get("end_col_offset_idx", 0)
                      - only.get("start_col_offset_idx", 0) >= cols)
        if any((grid[r][c] or {}).get("row_section") for c in present) or full_width:
            section = text(r, present[0])
            continue
        entry = UnitItem(name=None, section=section)
        for c in present:
            cell = grid[r][c] or {}
            if cell.get("start_col_offset_idx", c) < c:
                continue  # spanned cell already read at its first column
            evidence = doc.evidence(item, text(r, c), row=r, col=c, bbox=cell.get("bbox"))
            if c == name_col:
                entry.name, entry.name_evidence = text(r, c), evidence
            else:
                entry.values[labels[c]] = text(r, c)
                entry.evidence[labels[c]] = evidence
        unit.items.append(entry)


def structure_units(document: Any, document_id: str, *,
                    use_docling_core: bool = True) -> list[StructureUnit]:
    """List the structural units of one stored DoclingDocument JSON (or object), in reading order.

    The body tree is walked depth-first, the order of
    ``DoclingDocument.iterate_items(with_groups=True)``; heading context comes from ``TitleItem`` and
    ``SectionHeaderItem.level``; groups by ``GroupLabel`` (LIST/ORDERED_LIST, SHEET,
    KEY_VALUE_AREA/FORM_AREA); key-value pairs from ``KeyValueItem``/``FormItem.graph`` and
    ``FieldRegionItem``; tables through ``_table_view`` (``TableItem.export_to_dataframe``).
    """
    doc = _Doc(document, document_id, use_docling_core=use_docling_core)
    walker = _Walker(doc)
    walker.walk("#/body")
    # Units Docling left outside the body tree are still structure; read them without context.
    walker.headings, walker.preceding, walker.sheet = [], None, None
    for collection in ("tables", "key_value_items", "form_items", "field_regions"):
        for index in range(len(doc.raw.get(collection) or [])):
            walker.walk(f"#/{collection}/{index}")
    return walker.units


def unit_counts(units: list[StructureUnit]) -> dict[str, int]:
    counts = Counter(unit.kind for unit in units)
    return {kind: counts.get(kind, 0) for kind in _UNIT_KINDS}


# --------------------------------------------------------------------------- grouping


@dataclass
class CandidateRecord:
    key: str
    name: str
    names: list[str] = field(default_factory=list)
    values: dict[str, list[str]] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    sources: list[Evidence] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    units: list[str] = field(default_factory=list)


@dataclass
class CandidateCollection:
    id: str
    name: str | None
    names: list[str]
    kinds: list[str]
    units: list[str]
    documents: list[str]
    fields: list[str]
    records: list[CandidateRecord]
    unnamed_items: int = 0
    joined_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AmbiguousJoin:
    left: str
    right: str
    reason: str
    field_jaccard: float
    item_overlap: float
    shared_items: int


@dataclass
class Grouping:
    collections: list[CandidateCollection]
    ambiguous: list[AmbiguousJoin]

    def to_dict(self) -> dict:
        return {"collections": [c.to_dict() for c in self.collections],
                "ambiguous": [asdict(a) for a in self.ambiguous]}


def _field_keys(units: list[StructureUnit]) -> set[str]:
    return {key for unit in units for key in map(norm, unit.fields)
            if key and not re.fullmatch(r"col \d+", key)}


def _item_keys(units: list[StructureUnit]) -> set[str]:
    return {norm(item.name) for unit in units for item in unit.items if norm(item.name)}


def _name_keys(units: list[StructureUnit]) -> set[str]:
    return {norm(unit.name) for unit in units
            if unit.name_source not in {"none", "name_field"} and norm(unit.name)}


def _keys(units: list[StructureUnit]) -> tuple[set[str], set[str], set[str]]:
    return _field_keys(units), _item_keys(units), _name_keys(units)


def _signals(left: tuple[set[str], set[str], set[str]],
             right: tuple[set[str], set[str], set[str]]) -> tuple[float, float, int, bool]:
    (a, x, m), (b, y, n) = left, right
    jaccard = len(a & b) / len(a | b) if len(a) >= 2 and len(b) >= 2 else 0.0
    shared = len(x & y)
    overlap = shared / min(len(x), len(y)) if x and y else 0.0
    return round(jaccard, 4), round(overlap, 4), shared, bool(m & n)


def _strong(jaccard: float, overlap: float, shared: int, named: bool,
            min_shared: int = 1) -> list[str]:
    reasons = []
    if jaccard >= FIELD_JACCARD:
        reasons.append("fields")
    if named:
        reasons.append("name")
    if shared >= min_shared and overlap >= ITEM_OVERLAP:
        reasons.append("items")
    return reasons


def group_units(units: list[StructureUnit]) -> Grouping:
    """Deterministic candidate collections for one workspace; unsure joins are listed, not decided.

    Two units join when their normalized field sets overlap (Jaccard >= 0.6), their candidate names
    match after normalization, or at least half of the smaller unit's item names are shared. Pairs are
    applied strongest first. Joining two groups that already hold several units also needs the
    signal between the whole groups (items: at least two shared); otherwise, and for weaker
    overlaps, the pair is reported in ``ambiguous``. A single unit joins the first group it links to
    strongly; its further links are reported, never used to merge two collections.
    """
    pool = [u for u in units if u.kind != "sheet" and (u.items or u.fields)]
    pool.sort(key=lambda u: u.id)
    parent = {u.id: u.id for u in pool}
    members = {u.id: [u] for u in pool}
    reasons: dict[str, list[str]] = defaultdict(list)

    def find(uid: str) -> str:
        while parent[uid] != uid:
            parent[uid] = parent[parent[uid]]
            uid = parent[uid]
        return uid

    keys = {u.id: _keys([u]) for u in pool}
    pairs = []
    weak = []
    for i, left in enumerate(pool):
        for right in pool[i + 1:]:
            jaccard, overlap, shared, named = _signals(keys[left.id], keys[right.id])
            strong = _strong(jaccard, overlap, shared, named)
            score = max(jaccard, overlap if shared else 0.0, 1.0 if named else 0.0)
            if strong:
                pairs.append((-score, left.id, right.id, strong, jaccard, overlap, shared))
            elif jaccard >= WEAK_FIELD_JACCARD or (shared and overlap >= WEAK_ITEM_OVERLAP):
                weak.append(AmbiguousJoin(left.id, right.id, "weak_overlap", jaccard, overlap, shared))
    ambiguous: list[AmbiguousJoin] = []
    for _, left, right, strong, jaccard, overlap, shared in sorted(pairs):
        a, b = find(left), find(right)
        if a == b:
            continue
        if len(members[a]) > 1 and len(members[b]) > 1:
            # Whole groups need the signal themselves; one shared item is not enough.
            group = _strong(*_signals(_keys(members[a]), _keys(members[b])), min_shared=2)
            if not group:
                ambiguous.append(AmbiguousJoin(left, right, "would_bridge_collections",
                                               jaccard, overlap, shared))
                continue
        root, other = sorted((a, b))
        parent[other] = root
        members[root] = sorted(members[root] + members.pop(other), key=lambda u: u.id)
        reasons[root] = sorted(set(reasons[root]) | set(reasons.pop(other, [])) | set(strong))
    for join in weak:
        if find(join.left) != find(join.right):
            ambiguous.append(join)
    collections = [_collection(group, reasons.get(root, []))
                   for root, group in sorted(members.items())]
    collections.sort(key=lambda c: (-len(c.records), c.name or "", c.id))
    ambiguous.sort(key=lambda a: (a.left, a.right))
    return Grouping(collections, ambiguous)


def _choose_name(group: list[StructureUnit]) -> tuple[str | None, list[str]]:
    seen: dict[str, str] = {}
    score: Counter = Counter()
    for unit in group:
        key = norm(unit.name)
        if not key:
            continue
        seen.setdefault(key, unit.name or "")
        rank = NAME_SOURCES.index(unit.name_source) if unit.name_source in NAME_SOURCES else 99
        score[key] += 100 - rank
    if not score:
        return None, []
    ordered = sorted(score, key=lambda k: (-score[k], k))
    return seen[ordered[0]], [seen[k] for k in ordered]


def _collection(group: list[StructureUnit], joined_by: list[str]) -> CandidateCollection:
    name, names = _choose_name(group)
    labels: dict[str, str] = {}
    frequency: Counter = Counter()
    for unit in group:
        for label in unit.fields:
            key = norm(label) or label
            labels.setdefault(key, label)
            frequency[key] += 1
    records: dict[str, CandidateRecord] = {}
    seen_values: dict[tuple[str, str], set[str]] = defaultdict(set)
    unnamed = 0
    for unit in group:
        for item in unit.items:
            key = norm(item.name)
            if not key:
                unnamed += 1
                continue
            record = records.setdefault(key, CandidateRecord(key=key, name=item.name or ""))
            if item.name not in record.names:
                record.names.append(item.name or "")
            if item.name_evidence and item.name_evidence not in record.sources:
                record.sources.append(item.name_evidence)
            if unit.document_id not in record.documents:
                record.documents.append(unit.document_id)
            if unit.id not in record.units:
                record.units.append(unit.id)
            for label, value in item.values.items():
                display = labels.get(norm(label) or label, label)
                bucket = seen_values[(key, display)]
                if _value_key(value) in bucket:
                    continue
                bucket.add(_value_key(value))
                record.values.setdefault(display, []).append(value)
    for record in records.values():
        record.conflicts = sorted(f for f, values in record.values.items() if len(values) > 1)
    unit_ids = sorted(u.id for u in group)
    digest = sha256("\n".join(unit_ids).encode()).hexdigest()[:12]
    return CandidateCollection(
        id=f"cc_{digest}", name=name, names=names,
        kinds=sorted({u.kind for u in group}), units=unit_ids,
        documents=sorted({u.document_id for u in group}),
        fields=[labels[k] for k in sorted(frequency, key=lambda k: (-frequency[k], k))],
        records=sorted(records.values(), key=lambda r: r.key), unnamed_items=unnamed,
        joined_by=joined_by)
