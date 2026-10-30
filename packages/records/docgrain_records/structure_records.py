"""WP119 (decision 21): collections and records from Docling structure, before any model.

Each pinned document's stored DoclingDocument is read into structure units (``structure_units``:
tables, lists, key-value areas, sheets), the units of the whole workspace are grouped into
candidate collections (``group_units``) and every named item becomes a candidate record. Values
are never taken from Docling alone: each name and value is located in the pinned compact context
(the ``§N`` blocks every verifier and the merge use) and the candidate goes through the same
``verify_response`` as a model proposal. Table values cite their cell (``§N cell={...}`` with the
column header the verifier checks), list values their item block. What does not verify is dropped
and counted, so unsupported fields stay 0.

Documents whose verified structure covers less than ``MIN_COVERAGE`` of their text (or that have
no Docling structure at all) are listed for the model fallback, together with a reduced context
of the blocks structure did not cover. Unsure groupings become ``collection_merge`` questions;
answers (by stable unit-pair signatures) are applied on later runs. Pure functions: no network,
no model, no writes.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from hashlib import sha256

from .discovery_models import WorkspaceSchema
from .merge_models import CollectionMergeQuestion, CollectionMergeSide
from .models import RecordBase
from .normalize import fold
from .runtime import RESERVED, RuntimeRecords
from .structure_units import (
    AmbiguousJoin,
    StructureUnit,
    _collection,
    group_units,
    norm,
    structure_units,
    unit_counts,
)
from .structure_vocab import (
    COLLECTION_KEYS,
    FIELD_KEYS,
    known_collection_key,
    vocabulary_key,
)
from .verify import _blocks, _source_key, normalize_quote, verify_response

# Share of a document's (non-heading) text that verified structure must cover; below it the
# uncovered blocks go to the model when the workspace model is on.
MIN_COVERAGE = 0.5
# A collection needs two named items, or one item with at least one value.
MIN_RECORDS = 2
DESCRIPTION = "Built from the document structure (tables, lists, sheets); no model was used."

# KULLANILMIYOR (karar 18): eski sözlükler unused/wp122/structure_records.py içinde;
# ortak sözlükten yeniden dışa aktarılır, mevcut importlar korunur.
_ENGLISH_LABELS = {key: key.replace("_", " ").capitalize() for key in
                   set(FIELD_KEYS.values()) | set(COLLECTION_KEYS.values())}
_PLACEHOLDER = re.compile(r"col \d+|col_\d+|\d+")


# Small deterministic Russian transliteration; fold already normalizes accents/case.
_CYRILLIC = str.maketrans(dict(zip(
    "абвгдежзийклмнопрстуфхцчшщъыьэюяё",
    ("a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p",
     "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya", "e"),
    strict=True)))


def _slug(text: str, limit: int = 40) -> str:
    folded = fold(text or "")
    # ASCII identifiers are required by discovery_models.Key/CollectionKey.
    # KULLANILMIYOR (karar 18): ASCII-only dropping is archived in unused/wp122.
    folded = folded.replace("ı", "i").translate(_CYRILLIC)
    slug = re.sub(r"[^a-z0-9]+", "_", folded).strip("_")
    if len(slug) > limit:
        slug = slug[:limit].rsplit("_", 1)[0] or slug[:limit]
    return slug


def field_key(label: str) -> str:
    """English snake_case key: an obvious translation, else the normalized header."""
    folded = vocabulary_key(label)
    key = FIELD_KEYS.get(folded) or _slug(label) or "value"
    if not key[0].isalpha():
        key = "field_" + key
    if key in RESERVED or hasattr(RecordBase, key):
        key += "_value"
    return key


def collection_key(name: str | None) -> str:
    # KULLANILMIYOR (karar 18): exact-title lookup is archived in unused/wp122.
    if known := known_collection_key(name):
        return known
    slug = _slug(name or "") or "items"
    if not slug[0].isalpha():
        slug = "list_" + slug
    if slug.endswith("s"):
        return slug
    # Turkish plurals/possessives ("salonlari") are not English; keep them and mark the list.
    if re.search(r"(lar|ler|lari|leri|si|su)$", slug) or not (name or "").isascii():
        return slug + "_items"
    return slug + "s"


def _unique(key: str, used: set[str], plural: bool = False) -> str:
    if key not in used:
        used.add(key)
        return key
    index = 2
    while (candidate := f"{key}_{index}_items" if plural else f"{key}_{index}") in used:
        index += 1
    used.add(candidate)
    return candidate


def _labels(text: str, lang: str, english: str | None = None) -> list[dict]:
    labels = [{"lang": "en", "value": english or text}]
    if lang.split("-")[0] != "en" and lang != "und":
        labels.append({"lang": lang, "value": text})
    return labels


# --------------------------------------------------------------------------- locating evidence


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip("|").split("|")]


class SourceIndex:
    """The pinned compact context: §N blocks, their Markdown tables (as the verifier reads them)."""

    def __init__(self, context: str):
        normalized = _blocks(context)
        raw = _blocks(context, normalize=False)
        self.order = sorted((key for key in normalized if re.fullmatch(r"§\d+", key)),
                            key=lambda key: int(key[1:]))
        self.bodies = {key: normalized[key] for key in self.order}
        self.tables: dict[str, tuple[list[str], list[list[str]]]] = {}
        for key in self.order:
            lines = [normalize_quote(line) for line in raw[key].splitlines() if line.strip()]
            for index in range(len(lines) - 1):
                if lines[index].startswith("|") and re.fullmatch(r"\|[ :|\-]+\|", lines[index + 1]):
                    rows = []
                    for line in lines[index + 2:]:
                        if not line.startswith("|"):
                            break
                        rows.append(_cells(line))
                    self.tables[key] = (_cells(lines[index]), rows)
                    break

    def headings(self) -> set[str]:
        return {key for key, body in self.bodies.items() if body.startswith("#")}

    def table_for(self, texts: set[str]) -> str | None:
        best, score = None, 0
        for key, (headers, rows) in self.tables.items():
            cells = set(headers) | {cell for row in rows for cell in row}
            hit = len(texts & cells)
            if hit > score:
                best, score = key, hit
        return best

    def block_with(self, text: str, start: int = 0) -> str | None:
        """First block (from ``start`` in reading order, then from the top) stating ``text``."""
        if not text:
            return None
        ordered = self.order[start:] + self.order[:start]
        exact = [key for key in ordered
                 if re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", self.bodies[key]) == text]
        if exact:
            return exact[0]
        return next((key for key in ordered if text in self.bodies[key]), None)


def _cell_locator(key: str, row: int, column: int, header: str | None) -> str:
    cell = {"row": row + 1, "column": column + 1}
    if header and any(char.isalpha() for char in header) and not _PLACEHOLDER.fullmatch(header):
        cell["column_header"] = header
    return f"{key} cell=" + json.dumps(cell, ensure_ascii=False)


def _fact(document_id: str, lang: str, value: str, locator: str) -> dict:
    return {"value": value, "lang": lang,
            "evidence": [{"document_id": document_id, "locator": locator, "quote": value}]}


def _table_facts(unit: StructureUnit, source: SourceIndex, document_id: str, lang: str):
    """[(item, name_fact, {label: fact})] for a table unit, located in its Markdown table."""
    texts = {normalize_quote(item.name or "") for item in unit.items} | {
        normalize_quote(value) for item in unit.items for value in item.values.values()}
    key = source.table_for(texts - {""})
    headers, rows = source.tables.get(key, ([], [])) if key else ([], [])
    used: set[int] = set()
    result = []
    for item in unit.items:
        name = normalize_quote(item.name or "")
        if not name:
            continue
        row = column = None
        matches = [r for r, cells in enumerate(rows) if name in cells]
        if matches:
            row = next((r for r in matches if r not in used), matches[0])
            used.add(row)
            c = rows[row].index(name)
            name_fact = _fact(document_id, lang, name, _cell_locator(
                key, row, c, headers[c] if c < len(headers) else None))
        elif name in headers:  # transposed: the item is a column
            column = headers.index(name)
            name_fact = _fact(document_id, lang, name, key)
        else:
            block = source.block_with(name)
            if block is None:
                continue
            name_fact = _fact(document_id, lang, name, block)
        values = {}
        for label, raw in item.values.items():
            value = normalize_quote(raw)
            if not value:
                continue
            if row is not None:
                cells = rows[row]
                options = [c for c, cell in enumerate(cells) if cell == value]
                wanted = normalize_quote(label)
                c = next((c for c in options if c < len(headers) and headers[c] == wanted),
                         options[0] if options else None)
                if c is not None:
                    values[label] = _fact(document_id, lang, value, _cell_locator(
                        key, row, c, headers[c] if c < len(headers) else None))
                elif value in " | ".join(cells):
                    values[label] = _fact(document_id, lang, value, key)
            elif column is not None:
                r = next((r for r, cells in enumerate(rows)
                          if column < len(cells) and cells[column] == value), None)
                if r is not None:
                    values[label] = _fact(document_id, lang, value,
                                          _cell_locator(key, r, column, headers[column]))
            elif name_fact["evidence"][0]["locator"] in source.bodies and value in source.bodies[
                    name_fact["evidence"][0]["locator"]]:
                values[label] = _fact(document_id, lang, value, name_fact["evidence"][0]["locator"])
        result.append((item, name_fact, values))
    return result


def _list_facts(unit: StructureUnit, source: SourceIndex, document_id: str, lang: str):
    result = []
    position = 0
    for item in unit.items:
        name = normalize_quote(item.name or "")
        whole = normalize_quote(item.name_evidence.text if item.name_evidence else item.name or "")
        block = source.block_with(whole, position) or source.block_with(name, position)
        if not name or block is None or name not in source.bodies[block]:
            continue
        position = source.order.index(block) + 1
        values = {label: _fact(document_id, lang, normalize_quote(value), block)
                  for label, value in item.values.items()
                  if normalize_quote(value) and normalize_quote(value) in source.bodies[block]}
        result.append((item, _fact(document_id, lang, name, block), values))
    return result


# --------------------------------------------------------------------------- plan


def unit_signature(unit: StructureUnit) -> str:
    """Stable across file versions: document, kind, name and field labels (not Docling refs)."""
    payload = [unit.document_id, unit.kind, norm(unit.name),
               sorted({norm(label) for label in unit.fields} - {""})]
    return sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]


def pair_signature(left: StructureUnit, right: StructureUnit) -> str:
    pair = sorted([unit_signature(left), unit_signature(right)])
    return "cm_" + sha256("\n".join(pair).encode()).hexdigest()[:24]


@dataclass
class DocumentStructure:
    document_id: str
    filename: str | None
    docling: bool
    units: dict[str, int] = field(default_factory=dict)
    records: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    unlocated: int = 0
    coverage: float = 0.0
    covered: list[str] = field(default_factory=list)
    needs_model: bool = True

    def report(self) -> dict:
        return {"document_id": self.document_id, "filename": self.filename,
                "docling": self.docling, "units": self.units, "records": self.records,
                "rejected": self.rejected, "unlocated": self.unlocated,
                "coverage": round(self.coverage, 4), "needs_model": self.needs_model}


@dataclass
class StructurePlan:
    workspace_id: str
    schema: WorkspaceSchema | None
    candidates: dict[str, dict]
    documents: dict[str, DocumentStructure]
    questions: list[CollectionMergeQuestion]
    answered: list[str]

    @property
    def needs_model(self) -> list[str]:
        return sorted(key for key, doc in self.documents.items() if doc.needs_model)

    def report(self) -> dict:
        return {"collections": len(self.schema.collections) if self.schema else 0,
                "records": sum(doc.records for doc in self.documents.values()),
                "documents": [self.documents[key].report() for key in sorted(self.documents)],
                "documents_needing_model": self.needs_model,
                "collection_merge_questions": len(self.questions),
                "collection_merge_answers_applied": len(self.answered)}


def _apply_answers(units: list[StructureUnit], decisions: dict[str, bool]):
    """Group, then join the collections a person said are the same list; others stay apart."""
    grouping = group_units(units)
    by_id = {unit.id: unit for unit in units}
    owner = {uid: c.id for c in grouping.collections for uid in c.units}
    parent = {c.id: c.id for c in grouping.collections}

    def find(key):
        while parent[key] != key:
            key = parent[key]
        return key

    answered = []
    for join in grouping.ambiguous:
        signature = pair_signature(by_id[join.left], by_id[join.right])
        if decisions.get(signature) is True:
            a, b = find(owner[join.left]), find(owner[join.right])
            if a != b:
                parent[max(a, b)] = min(a, b)
            answered.append(signature)
        elif decisions.get(signature) is False:
            answered.append(signature)
    members = defaultdict(list)
    for collection in grouping.collections:
        members[find(collection.id)].append(collection)
    collections = []
    for group in members.values():
        if len(group) == 1:
            collections.append(group[0])
            continue
        joined = sorted({reason for c in group for reason in c.joined_by} | {"answer"})
        merged = _collection([by_id[uid] for c in group for uid in c.units], joined)
        # The joined list keeps the name of its largest part (as the immediate answer does).
        largest = min(group, key=lambda c: (-len(c.records), c.name or "", c.id))
        if largest.name:
            merged.name = largest.name
            merged.names = [largest.name, *[n for n in merged.names if n != largest.name]]
        collections.append(merged)
    collections.sort(key=lambda c: (-len(c.records), c.name or "", c.id))
    owner = {uid: c.id for c in collections for uid in c.units}
    open_joins = [join for join in grouping.ambiguous
                  if pair_signature(by_id[join.left], by_id[join.right]) not in decisions
                  and owner[join.left] != owner[join.right]]
    return collections, open_joins, sorted(set(answered))


def build_structure_plan(documents, doclings: dict[str, dict | None], workspace_id: str,
                         decisions: dict[str, bool] | None = None, *,
                         min_coverage: float = MIN_COVERAGE) -> StructurePlan:
    """``documents``: pinned ``DiscoveryDocument``s; ``doclings``: document_id -> Docling JSON."""
    decisions = decisions or {}
    sources = {doc.source.document_id: doc for doc in documents}
    reports = {key: DocumentStructure(key, doc.source.filename, bool(doclings.get(key)))
               for key, doc in sources.items()}
    units: list[StructureUnit] = []
    for key in sorted(sources):
        found = structure_units(doclings[key], key) if doclings.get(key) else []
        reports[key].units = unit_counts(found)
        units.extend(found)
    collections, open_joins, answered = _apply_answers(units, decisions)
    by_id = {unit.id: unit for unit in units}
    indexes = {key: SourceIndex(doc.context) for key, doc in sources.items()}
    langs = {key: doc.source.lang for key, doc in sources.items()}

    # 1. Locate every named item and value in its pinned context.
    used_keys: set[str] = set()
    planned: list[_Planned] = []
    for collection in collections:
        located = []
        for uid in collection.units:
            unit = by_id[uid]
            locate = {"table": _table_facts, "list": _list_facts}.get(unit.kind)
            if locate is None:
                continue  # Key-value areas have no item names; they stay for the model path.
            document = unit.document_id
            facts = locate(unit, indexes[document], document, langs[document])
            reports[document].unlocated += sum(1 for item in unit.items if item.name) - len(facts)
            located.extend((document, name, values) for _item, name, values in facts)
        if not located:
            continue
        names = {fold(name["value"]) for _, name, _ in located}
        if len(names) < MIN_RECORDS and not any(values for *_, values in located):
            continue
        title = collection.name or (collection.names[0] if collection.names else None)
        entry = _Planned(key=_unique(collection_key(title or "items"), used_keys, plural=True),
                         title=title or "Liste", collection=collection, located=located,
                         lang=langs[located[0][0]])
        for unit in (by_id[uid] for uid in collection.units):
            if unit.name_field and not _PLACEHOLDER.fullmatch(norm(unit.name_field)):
                entry.name_label = unit.name_field
                break
        for *_, values in located:
            for label in values:
                folded = norm(label) or label
                if folded not in entry.field_keys:
                    key = field_key(label)
                    entry.field_keys[folded] = "other_name" if key == "name" else key
                    entry.labels.setdefault(entry.field_keys[folded], label)
        planned.append(entry)

    # 2. Verify with a temporary accepted contract, exactly as a model proposal is verified.
    temporary = _schema(workspace_id, planned, lambda entry, key: entry.located_fact(key))
    verified = {}
    if temporary["collections"]:
        temporary.update(review_state="accepted", version=1)
        for collection in temporary["collections"]:
            collection["review_state"] = "accepted"
            for definition in collection["fields"]:
                definition["review_state"] = "accepted"
        runtime = RuntimeRecords(temporary)
        for document, raw in _candidates(planned).items():
            doc = sources[document]
            verified[document] = verify_response(json.dumps(raw, ensure_ascii=False), doc.context,
                                                 document, doc.source.lang, runtime=runtime)

    # 3. Keep what verified: fields with a verified value, collections with a verified name.
    supported: dict[str, set[str]] = defaultdict(set)
    proof: dict[tuple[str, str], dict] = {}
    for document, result in sorted(verified.items()):
        report = reports[document]
        report.rejected = dict(sorted(Counter(item.reason for item in result.rejected).items()))
        covered = set()
        for record in result.records:
            for fields in [record, *record.i18n.values()]:
                for name in runtime.models[record.type][1].model_fields:
                    fact = getattr(fields, name)
                    if fact is None:
                        continue
                    supported[record.type].add(name)
                    first = fact.evidence[0]
                    proof.setdefault((record.type, name), {
                        "value": fact.value, "lang": fact.lang,
                        "evidence": [{"document_id": first.document_id, "locator": first.locator,
                                      "quote": first.quote}]})
                    covered.update(_source_key(e.locator) for e in fact.evidence)
        report.records = len(result.records)
        report.covered = sorted(covered)
    kept = [entry for entry in planned if "name" in supported.get(entry.key, set())]
    for entry in kept:
        entry.keep = supported[entry.key]
    final = _schema(workspace_id, kept, lambda entry, key: proof.get((entry.key, key)))
    schema = WorkspaceSchema.model_validate(final) if final["collections"] else None
    candidates = _candidates(kept)

    # 4. Coverage of each document's text by verified structure evidence.
    for key, report in reports.items():
        index = indexes[key]
        headings = index.headings()
        body = {k: len(v) for k, v in index.bodies.items() if k not in headings}
        total = sum(body.values())
        covered = set(report.covered)
        hit = sum(length for k, length in body.items() if k in covered)
        report.coverage = hit / total if total else (1.0 if report.records else 0.0)
        report.needs_model = not report.records or report.coverage < min_coverage

    # 5. One question per pair of kept collections that an unsure grouping links.
    owner = {uid: entry for entry in kept for uid in entry.collection.units}
    pairs: dict[tuple[str, str], list] = defaultdict(list)
    for join in open_joins:
        left, right = owner.get(join.left), owner.get(join.right)
        if left is None or right is None or left.key == right.key:
            continue
        # The larger list is "left": a "same" answer keeps its key and name.
        ordered = sorted((left, right), key=lambda e: (-len({fold(n["value"]) for _, n, _ in e.located}),
                                                       e.key))
        pairs[(ordered[0].key, ordered[1].key)].append(join)
    entries = {entry.key: entry for entry in kept}
    questions = [CollectionMergeQuestion(
        signatures=sorted({pair_signature(by_id[j.left], by_id[j.right]) for j in joins}),
        reason=_reason(joins), left=entries[left].side(), right=entries[right].side())
        for (left, right), joins in sorted(pairs.items())]
    return StructurePlan(workspace_id, schema, candidates, reports, questions, answered)


@dataclass
class _Planned:
    """One collection on its way to the schema: located facts per document, field keys."""

    key: str
    title: str
    collection: object
    located: list  # [(document_id, name fact, {source label: fact})]
    lang: str
    name_label: str = "Ad"
    field_keys: dict[str, str] = field(default_factory=dict)  # folded label -> field key
    labels: dict[str, str] = field(default_factory=dict)  # field key -> source label
    keep: set[str] | None = None

    def field_names(self) -> list[str]:
        keys = ["name", *sorted(self.labels)]
        return [k for k in keys if self.keep is None or k in self.keep]

    def target(self, label: str) -> str:
        return self.field_keys[norm(label) or label]

    def located_fact(self, key: str) -> dict | None:
        for _, name, values in self.located:
            if key == "name":
                return name
            for label, fact in values.items():
                if self.target(label) == key:
                    return fact
        return None

    def side(self) -> CollectionMergeSide:
        names = list(dict.fromkeys(name["value"] for _, name, _ in self.located))
        return CollectionMergeSide(collection=self.key, label=self.title, records=names[:5],
                                   record_count=len(names),
                                   documents=sorted({document for document, _, _ in self.located}))


def _schema(workspace_id: str, entries: list[_Planned], example) -> dict:
    """Proposed workspace schema: string fields, one verified example value per field."""
    collections = []
    for entry in entries:
        fields, examples = [], []
        for key in entry.field_names():
            fact = example(entry, key)
            if fact is None:
                continue
            label = entry.name_label if key == "name" else entry.labels[key]
            if label == "detail":
                label = "Ayrıntı"
            fields.append({"key": key, "type": "string", "unit": None,
                           "label_i18n": _labels(label, entry.lang, _ENGLISH_LABELS.get(key)),
                           "review_state": "proposed", "alternatives": []})
            examples.append({"values": [{"key": key, **fact}]})
        if not any(f["key"] == "name" for f in fields):
            continue
        collections.append({
            "key": entry.key, "label_i18n": _labels(entry.title, entry.lang,
                                                    _ENGLISH_LABELS.get(entry.key)),
            "description": DESCRIPTION, "fields": fields, "examples": examples,
            "aliases": [], "review_state": "proposed"})
    return {"workspace_id": workspace_id, "sources": [], "collections": collections}


def _candidates(entries: list[_Planned]) -> dict[str, dict]:
    """Per document the proposal JSON verify_response reads: one record per located item."""
    records: dict[str, list] = defaultdict(list)
    for entry in entries:
        keys = entry.field_names()
        for document, name, values in entry.located:
            record = {"type": entry.key, **{key: [] for key in keys}, "name": [name]}
            for label, fact in values.items():
                target = entry.target(label)
                if target in record and target != "name" and not record[target]:
                    record[target] = [fact]
            records[document].append(record)
    return {document: {"records": items} for document, items in sorted(records.items())}


def _reason(joins: list[AmbiguousJoin]) -> str:
    return "would_bridge_collections" if any(
        j.reason == "would_bridge_collections" for j in joins) else "weak_overlap"


def reduced_context(context: str, covered: set[str] | list[str]) -> str:
    """The context without blocks structure already covered (headings and footer stay).

    Every kept block keeps its ``[§N p.X]`` key, so model evidence stays valid in the full context.
    """
    covered = set(covered)
    if not covered:
        return context
    markers = list(re.finditer(r"(?m)^\[§(\d+) p\.[^\r\n]*\]\r?$", context))
    footer = re.search(r"(?m)^## Kaynak anahtarları\r?$", context)
    boundary = footer.start() if footer else len(context)
    if not markers:
        return context
    parts = [context[:markers[0].start()]]
    for index, marker in enumerate(markers):
        if marker.start() >= boundary:
            break
        stop = markers[index + 1].start() if index + 1 < len(markers) else boundary
        stop = min(stop, boundary)
        body = context[marker.end():stop].strip()
        if f"§{marker.group(1)}" not in covered or body.startswith("#"):
            parts.append(context[marker.start():stop])
    parts.append(context[boundary:])
    return "".join(parts)

