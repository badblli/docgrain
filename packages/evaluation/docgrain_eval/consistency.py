"""Offline, source-text-free reports for pinned extraction/merge artifacts.

The records extra is loaded only by these commands. No API or model is invoked.
"""

import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from docgrain_records.api import SourceMetadata
from docgrain_records.export import load_revision, project_records
from docgrain_records.match import load_records
from docgrain_records.match_merge import load_merge_documents, runtime_for_results
from docgrain_records.runtime import revision_runtime
from docgrain_records.verify import _blocks, _source_key, normalize_quote


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))


def token(value):
    """Report references never expose names, quotes, paths or source-derived IDs."""
    return sha256(encode(value).encode("utf-8")).hexdigest()[:16]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass
class Run:
    workspace: str
    pins: list[dict]
    schema: dict | None
    collections: dict
    identities: dict
    records: list[dict]
    mode: str
    failures: int = 0
    match_issues: int = 0
    context_hashes: dict | None = None


def _pin(pin):
    result = {key: pin[key] for key in (
        "document_id", "source_version_id", "knowledge_revision_id", "content_sha256")}
    if not result["content_sha256"]:
        raise ValueError("measurement requires content hashes on every source pin")
    result["content_sha256"] = result["content_sha256"].lower()
    return result


def load_run(path):
    root = Path(path)
    revisions = [root] if root.is_file() else sorted(root.rglob("merge_revision.json"))
    if len(revisions) > 1:
        raise ValueError("choose one merge revision; multiple revisions are ambiguous")
    if revisions:
        revision = load_revision(revisions[0].read_bytes())
        runtime = revision_runtime(revision)
        # Validate schema fields, values, duplicate IDs and publication approval gates.
        project_records(revision, mode="approved")
        pins = [_pin(pin.model_dump(mode="json")) for pin in revision.documents]
        if len({pin["document_id"] for pin in pins}) != len(pins):
            raise ValueError("revision has duplicate document pins")
        return Run(revision.workspace_id, pins, runtime.schema, runtime.collections,
                   runtime.identities, [r.model_dump(mode="json") for r in revision.records],
                   "merge", match_issues=len(revision.match_issues))
    results = load_records(root)
    runtime = runtime_for_results(results)
    documents = load_merge_documents(root, results, runtime=runtime)
    records = []
    for document in documents:
        for item in document.records:
            record = item.record
            fields = {}
            for name in record.field_names():
                primary = getattr(record, name)
                localized = {lang: fact.model_dump(mode="json")
                             for lang, group in record.i18n.items()
                             if (fact := getattr(group, name)) is not None}
                conflicts = [fact.model_dump(mode="json")
                             for fact in record.conflicts.get(name, [])]
                if primary or localized or conflicts:
                    fields[name] = {"primary": primary.model_dump(mode="json") if primary else None,
                                    "i18n": localized, "conflicts": conflicts}
            records.append({"id": record.id, "type": record.type, "fields": fields,
                            "scope": document.document_id, "review_state": record.review_state})
    return Run(documents[0].workspace_id,
               [_pin(document.model_dump(mode="json")) for document in documents],
               runtime.schema, runtime.collections, runtime.identities, records, "extraction",
               failures=sum(len(result.failures) for result in results),
               context_hashes={document.document_id: sha256(document.context.encode()).hexdigest()
                               for document in documents})


def _fact(fact):
    return {"value": fact["value"], "lang": fact["lang"],
            "review_state": fact.get("review_state"),
            "evidence": sorted({encode({**e, "quote": normalize_quote(e["quote"])})
                                for e in fact["evidence"]})}


def _field(field, mode):
    if mode == "merge":
        return {"primary_lang": field["primary_lang"],
                "candidates": sorted(encode(_fact(fact)) for fact in field["candidates"])}
    return {"primary": _fact(field["primary"]) if field["primary"] else None,
            "i18n": {lang: _fact(fact) for lang, fact in field["i18n"].items()},
            "conflicts": sorted(encode(_fact(fact)) for fact in field["conflicts"])}


def facts(field, mode):
    if mode == "merge":
        return field["candidates"]
    return ([field["primary"]] if field["primary"] else []) + list(
        field["i18n"].values()) + field["conflicts"]


def _anchor(record, run):
    identity = record["fields"].get(run.identities[record["type"]])
    names = sorted({encode([fact["lang"], fact["value"]]) for fact in facts(identity, run.mode)
                    if fact.get("review_state") != "rejected"}) if identity else []
    return encode([record.get("scope"), record["type"], names])


def _view(record, run):
    return {"review_state": record.get("review_state"),
            "fields": {key: _field(field, run.mode) for key, field in record["fields"].items()}}


def _groups(run):
    groups = defaultdict(list)
    for record in run.records:
        groups[_anchor(record, run)].append(_view(record, run))
    return groups


def _rate(identical, total):
    return {"identical": identical, "total": total, "rate": identical / total if total else None}


def stability(before, after):
    if before.mode != after.mode:
        raise ValueError("compare two extraction runs or two merge revisions")
    if before.workspace != after.workspace or sorted(map(encode, before.pins)) != sorted(map(encode, after.pins)):
        raise ValueError("runs do not have identical workspace/source pins")
    if before.schema != after.schema:
        raise ValueError("runs do not have the same accepted schema snapshot")
    if before.context_hashes != after.context_hashes:
        raise ValueError("runs do not have identical local source contexts")
    left, right = _groups(before), _groups(after)
    records_same = records_total = fields_same = fields_total = 0
    changed = []
    for anchor in sorted(left.keys() | right.keys()):
        a, b = left[anchor], right[anchor]
        ca, cb = Counter(map(encode, a)), Counter(map(encode, b))
        common = ca & cb
        records_same += common.total()
        records_total += max(len(a), len(b))
        # Pair identical occurrences first; multiplicity must never disappear.
        pairs = [(json.loads(key), json.loads(key)) for key, count in sorted(common.items())
                 for _ in range(count)]
        remaining_a = sorted((ca - common).elements())
        remaining_b = sorted((cb - common).elements())
        for index in range(max(len(remaining_a), len(remaining_b))):
            pairs.append((json.loads(remaining_a[index]) if index < len(remaining_a) else {"fields": {}},
                          json.loads(remaining_b[index]) if index < len(remaining_b) else {"fields": {}}))
        for a_record, b_record in pairs:
            for field in sorted(a_record["fields"].keys() | b_record["fields"].keys()):
                same = (field in a_record["fields"] and field in b_record["fields"]
                        and a_record["fields"][field] == b_record["fields"][field])
                fields_same += same
                fields_total += 1
                if not same:
                    changed.append({"record_ref": token(anchor), "field": field})
    return {"format": "docgrain.stability", "version": 1, "mode": before.mode,
            "workspace_ref": token(before.workspace), "source_pins_identical": True,
            "input_verification": "pins_and_contexts" if before.context_hashes is not None else "pins_only",
            "extraction_failures": [before.failures, after.failures],
            "records": _rate(records_same, records_total), "fields": _rate(fields_same, fields_total),
            "changed_fields": changed}


def load_sources(path, workspace):
    sources = {}
    for metadata in sorted(Path(path).rglob("source.json")):
        pin = SourceMetadata.model_validate_json(metadata.read_text(encoding="utf-8"))
        if pin.workspace_id != workspace:
            raise ValueError("source directory contains a different workspace")
        if pin.document_id in sources:
            raise ValueError("source directory has ambiguous document versions")
        context = (metadata.parent / "context.md").read_text(encoding="utf-8")
        sources[pin.document_id] = (_pin(pin.model_dump(mode="json")), context, _blocks(context))
    return sources


def evidence_failure(evidence, pins, sources):
    doc = evidence["document_id"]
    pin = pins.get(doc)
    if pin is None:
        return "document_not_pinned"
    if any(evidence.get(key) != pin[key] for key in ("source_version_id", "knowledge_revision_id")):
        return "evidence_pin_mismatch"
    if doc not in sources:
        return "source_missing"
    source_pin, _, blocks = sources[doc]
    if pin != source_pin:
        return "source_pin_mismatch"
    block = blocks.get(_source_key(evidence["locator"]))
    if block is None:
        return "locator_not_found"
    quote = normalize_quote(evidence["quote"])
    return None if quote and quote in block else "quote_not_found"


def support(run, sources):
    if run.mode != "merge":
        raise ValueError("support requires a merge revision")
    pins = {pin["document_id"]: pin for pin in run.pins}
    total = unsupported = 0
    reasons = Counter()
    failed = []
    for record in run.records:
        for field, merged in record["fields"].items():
            for fact in merged["candidates"]:
                if fact["review_state"] != "accepted":
                    continue
                total += 1
                errors = {reason for e in fact["evidence"]
                          if (reason := evidence_failure(e, pins, sources)) is not None}
                if errors:
                    unsupported += 1
                    reasons.update(errors)
                    failed.append({"record_ref": token(record["id"]), "field": field,
                                   "lang": fact["lang"], "reasons": sorted(errors)})
    return {"format": "docgrain.support", "version": 1, "scope": "approved_field_languages",
            "published_fields": total, "unsupported_fields": unsupported,
            "unsupported_field_rate": unsupported / total if total else None,
            "target_met": total > 0 and unsupported == 0,
            "failure_reasons": dict(sorted(reasons.items())), "failures": failed,
            "coverage": coverage(run, sources)}


def _rows(context):
    """Enumerate compact Markdown rows before looking at any predictions."""
    boundary = context.find("\n## Kaynak anahtarları")
    body = context[:boundary] if boundary >= 0 else context
    locator = None
    lines = body.splitlines()
    for index, line in enumerate(lines):
        marker = re.fullmatch(r"\[§(\d+) p\.[^\r\n]*\]", line)
        if marker:
            locator = "§" + marker[1]
        if locator is None:
            continue
        # The separator identifies the header, including generated numeric headers.
        table = line.startswith("|") and line.endswith("|")
        if table:
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
            if not any(cells) or all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                continue
            if index + 1 < len(lines) and re.fullmatch(r"[|\s:\-]+", lines[index + 1]):
                continue
            identity = next((cell for cell in cells if cell), "")
            yield locator, "table", normalize_quote(identity), normalize_quote(line)
        elif match := re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(\S.*)$", line):
            yield locator, "list", normalize_quote(match[1]), normalize_quote(match[1])


def coverage(run, sources):
    pins = {pin["document_id"]: pin for pin in run.pins}
    # Extraction evidence lacks version IDs; add the artifact's own pin for validation.
    quotes = defaultdict(list)
    for record in run.records:
        for field in record["fields"].values():
            for fact in facts(field, run.mode):
                if fact.get("review_state") == "rejected":
                    continue
                for original in fact["evidence"]:
                    doc = original["document_id"]
                    e = {**pins.get(doc, {}), **original}
                    if evidence_failure(e, pins, sources) is None:
                        locator = _source_key(e["locator"])
                        aliases = {object_id: "§" + key for key, object_id in re.findall(
                            r"(?m)^§(\d+) → (\S+)(?: · [^\r\n]*)?\r?$", sources[doc][1])}
                        quotes[doc, aliases.get(locator, locator)].append(normalize_quote(e["quote"]))
    total = covered = ambiguous = 0
    kinds = Counter()
    unavailable = len(pins.keys() - sources.keys())
    for doc, pin in pins.items():
        if doc not in sources:
            continue
        if sources[doc][0] != pin:
            unavailable += 1
            continue
        rows = list(_rows(sources[doc][1]))
        counts = Counter((locator, identity) for locator, _, identity, _ in rows)
        for locator, kind, identity, row in rows:
            total += 1
            kinds[kind] += 1
            # Shared/empty/numeric cell fragments cannot establish a row identity.
            if counts[locator, identity] > 1 or not re.search(r"[^\W\d_]", identity):
                ambiguous += 1
                continue
            covered += any(identity in quote and (quote in row or row in quote)
                           for quote in quotes[doc, locator])
    return {"scope": "detected_markdown_list_table_rows", "source_rows": total,
            "covered_rows": covered, "ambiguous_rows": ambiguous, "row_kinds": dict(kinds),
            "unavailable_sources": unavailable,
            "rate": covered / total if total and not unavailable else None}


def normalized_name(value):
    value = unicodedata.normalize("NFKC", value).casefold().replace("ı", "i")
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    words = re.findall(r"[a-z0-9]+", value)
    generic = {"room", "rooms", "oda", "odasi", "zimmer", "the"}
    return " ".join("suite" if word == "suit" else word for word in words if word not in generic)


def company_summary(run, sources=None):
    counts = {collection: 0 for collection in run.collections.values()}
    conflicts = Counter()
    names = defaultdict(set)
    for record in run.records:
        collection = run.collections[record["type"]]
        counts[collection] += 1
        identity = run.identities[record["type"]]
        for field, value in record["fields"].items():
            candidates = facts(value, run.mode)
            by_lang = defaultdict(set)
            for fact in candidates:
                if fact.get("review_state") == "rejected":
                    continue
                by_lang[fact["lang"]].add(encode(fact["value"]))
                if field == identity and isinstance(fact["value"], str):
                    name = normalized_name(fact["value"])
                    if name:
                        names[collection, name].add(token([record.get("scope"), record["id"]]))
            conflicts[collection] += sum(len(values) > 1 for values in by_lang.values())
    duplicates = [{"collection": collection, "name_ref": token(name), "record_refs": sorted(refs)}
                  for (collection, name), refs in sorted(names.items()) if len(refs) > 1]
    return {"workspace_ref": token(run.workspace), "mode": run.mode,
            "collections": [{"key": key, "records": count, "conflicting_field_languages": conflicts[key]}
                            for key, count in sorted(counts.items())],
            "possible_duplicates": duplicates, "match_issues": run.match_issues,
            "extraction_failures": run.failures,
            "coverage": coverage(run, sources) if sources is not None else None,
            "support": support(run, sources) if sources is not None and run.mode == "merge" else None,
            "accuracy": {"status": "not_measured", "reason": "independent_keys_required"}}


def bundle_summary(paths, run):
    files = []
    matched = False
    for path in paths:
        report = read_json(path)
        if not isinstance(report, dict) or "workspace_id" not in report or "files" not in report:
            raise ValueError("bundle report has invalid structure")
        if report["workspace_id"] == run.workspace:
            matched = True
            files.extend(report["files"])
    if not matched:
        return None
    statuses = {"done", "partial", "failed", "skipped", "error", "timeout"}
    if any(row.get("status") not in statuses for row in files):
        raise ValueError("bundle report has an unknown processing status")
    documents = {row["document_id"] for row in files if row.get("document_id")}
    pinned = {pin["document_id"] for pin in run.pins}
    return {"files": len(files), "statuses": dict(sorted(Counter(row["status"] for row in files).items())),
            "documents": len(documents), "documents_in_run": len(documents & pinned),
            "documents_missing_from_run": len(documents - pinned),
            "run_documents_absent_from_bundle": len(pinned - documents),
            "issue_count": sum(len(row.get("issues", [])) for row in files)}


def percent(value):
    return "ölçülmedi" if value is None else f"{value:.1%}"


def run_stability(args):
    result = stability(*(load_run(path) for path in args.runs))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "stability.json", result)
    (out / "stability.md").write_text(
        "# Tekrar işleme kararlılığı\n\n"
        + "\n".join(f"- {label}: {result[key]['identical']}/{result[key]['total']} "
                    f"({percent(result[key]['rate'])})" for key, label in (("records", "Kayıtlar"), ("fields", "Alanlar")))
        + f"\n- Tamamlanmayan taramalar: {result['extraction_failures']}\n", encoding="utf-8")
    print("Kararlılık raporu hazır.")


def run_support(args):
    run = load_run(args.revision)
    result = support(run, load_sources(args.sources, run.workspace))
    if args.out:
        write_json(args.out, result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def run_companies(args):
    bundles = []
    for path in args.bundles or []:
        root = Path(path)
        bundles.extend(sorted(root.glob("*.json")) if root.is_dir() else [root])
    companies = []
    seen = set()
    for path in args.workspaces:
        run = load_run(path)
        if run.workspace in seen:
            raise ValueError("companies requires distinct workspaces")
        seen.add(run.workspace)
        root = Path(path).parent if Path(path).is_file() else Path(path)
        sources = load_sources(root, run.workspace)
        company = company_summary(run, sources or None)
        company["bundle"] = bundle_summary(bundles, run)
        companies.append(company)
    result = {"format": "docgrain.companies", "version": 1, "companies": companies}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out.with_suffix(".json"), result)
    lines = ["# Şirketler arası bilgi raporu", "",
             "Şirket adları, kayıt adları ve kaynak metni rapora alınmaz. Yinelenme bulguları inceleme önerisidir.", "",
             "| Şirket | Bilgi listesi | Kayıt | Çelişen alan/dil |",
             "| --- | --- | ---: | ---: |"]
    for index, company in enumerate(companies, 1):
        for collection in company["collections"]:
            lines.append(f"| Şirket {index} | {collection['key']} | {collection['records']} | "
                         f"{collection['conflicting_field_languages']} |")
    for index, company in enumerate(companies, 1):
        lines.extend(["", f"## Şirket {index}", "",
                      f"- Olası yinelenen kayıt grubu: {len(company['possible_duplicates'])}",
                      f"- Eşleştirme sorunu: {company['match_issues']}",
                      f"- Tamamlanmayan tarama: {company['extraction_failures']}",
                      "- Alan doğruluğu: ölçülmedi; bağımsız anahtar gerekli."])
        if company["support"]:
            s = company["support"]
            lines.append(f"- Kanıtsız onaylı alan: {s['unsupported_fields']}/{s['published_fields']} "
                         f"({percent(s['unsupported_field_rate'])})")
        else:
            lines.append("- Kanıtsız onaylı alan: ölçülmedi.")
        if company["coverage"]:
            c = company["coverage"]
            lines.append(f"- Kaynak satırı kapsamı: {c['covered_rows']}/{c['source_rows']} "
                         f"({percent(c['rate'])}); belirsiz satır: {c['ambiguous_rows']}")
        else:
            lines.append("- Kaynak satırı kapsamı: ölçülmedi.")
        if company["bundle"]:
            b = company["bundle"]
            lines.append(f"- Yükleme: {b['files']} dosya; durumlar: {encode(b['statuses'])}; "
                         f"çıktıda eksik belge: {b['documents_missing_from_run']}; sorun: {b['issue_count']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Şirket karşılaştırma raporu hazır.")
