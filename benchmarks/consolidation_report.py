"""Offline WP114 consolidation audit. Writes private JSON + Turkish Markdown; no model calls."""

import argparse
import json
import sys
from collections import Counter
from difflib import SequenceMatcher
from hashlib import sha256
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for package in ("domain", "evaluation", "records", "access"):
    sys.path.insert(0, str(ROOT / "packages" / package))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from docgrain_records.auto_accept import _groups
from docgrain_records.export import load_revision
from docgrain_records.match import load_records, transliterate
from docgrain_records.merge_models import VersionedEvidence
from docgrain_records.normalize import mentions
from docgrain_records.runtime import revision_runtime
from docgrain_records.structure_context import StructureIndex, context_signature
from docgrain_records.verify import _blocks, _source_key, normalize_quote


def _names(record, identity):
    return [(c.lang, transliterate(normalize_quote(str(c.value))))
            for c in record.fields.get(identity, ()).candidates] if identity in record.fields else []


def build_report(revision, results=(), contexts=None):
    """Audit immutable input, including old name-only merges via original context.md."""
    contexts = contexts or {}
    indexes = {document: StructureIndex(text) for document, text in contexts.items()}
    blocks = {document: _blocks(text) for document, text in contexts.items()}
    runtime = revision_runtime(revision)
    pins = {(p.document_id, p.source_version_id, p.knowledge_revision_id) for p in revision.documents}
    counts = Counter({collection: 0 for collection in runtime.collections.values()})
    over, under, real, formatting, unsupported = [], [], [], [], []
    for record in sorted(revision.records, key=lambda r: r.id):
        collection = runtime.collections[record.type]
        counts[collection] += 1
        for field, merged in sorted(record.fields.items()):
            # Include rejected variants in the format-only audit, but user-rejected
            # alternatives do not count as current real conflicts.
            for lang in sorted({c.lang for c in merged.candidates}):
                slot = [c for c in merged.candidates if c.lang == lang]
                active = [c for c in slot if c.review_state != "rejected"]
                detail = {"collection": collection, "record_id": record.id, "field": field, "lang": lang}
                if len(slot) > 1 and len(_groups(field, slot)) == 1:
                    formatting.append(detail)
                if len(active) > 1 and len(_groups(field, active)) > 1:
                    real.append(detail)
                    for a, b in combinations(active, 2):
                        for ea in a.evidence:
                            for eb in b.evidence:
                                if (not isinstance(ea, VersionedEvidence) or not isinstance(eb, VersionedEvidence)
                                        or ea.document_id != eb.document_id):
                                    continue
                                index = indexes.get(ea.document_id)
                                ca = index.at(ea.locator, ea.quote) if index else ea.structure_context
                                cb = index.at(eb.locator, eb.quote) if index else eb.structure_context
                                if ca and cb and any(context_signature(ca)) and any(context_signature(cb)) \
                                        and context_signature(ca) != context_signature(cb):
                                    reason = "different_structure"
                                elif _source_key(ea.locator) != _source_key(eb.locator):
                                    # Weaker: no distinguishing headings (e.g. drawing labels), yet one
                                    # document states different values in different blocks.
                                    reason = "same_document_different_blocks"
                                else:
                                    continue
                                suspect = detail | {"document_id": ea.document_id, "reason": reason,
                                                    "locators": [ea.locator, eb.locator],
                                                    "contexts": [c.model_dump() if c else None
                                                                 for c in (ca, cb)]}
                                if suspect not in over:
                                    over.append(suspect)
            for candidate in merged.candidates:
                if candidate.review_state == "rejected":
                    continue
                valid = True
                for e in candidate.evidence:
                    if not isinstance(e, VersionedEvidence):
                        valid &= e.kind == "user_edit"
                        continue
                    valid &= ((e.document_id, e.source_version_id, e.knowledge_revision_id) in pins
                              and e.document_id in contexts
                              and normalize_quote(e.quote) in blocks[e.document_id].get(
                                  _source_key(e.locator), normalize_quote(contexts[e.document_id])
                                  if not blocks[e.document_id] else "")
                              and mentions(e.quote, candidate.value, field))
                if not valid:
                    unsupported.append({"record_id": record.id, "field": field, "candidate_id": candidate.id})
    for a, b in combinations(sorted(revision.records, key=lambda r: r.id), 2):
        if a.type != b.type:
            continue
        identity = runtime.identities[a.type]
        pairs = [(la, na, lb, nb) for la, na in _names(a, identity) for lb, nb in _names(b, identity)]
        similarity = max((SequenceMatcher(None, na, nb, autojunk=False).ratio()
                          for _, na, _, nb in pairs), default=0)
        numeric_agreement = sum(
            type(ca.value) in {int, float} and type(cb.value) in {int, float} and ca.value == cb.value
            for field in a.fields.keys() & b.fields.keys() if field != identity
            for ca in a.fields[field].candidates for cb in b.fields[field].candidates)
        possible_translation = numeric_agreement >= 2 and any(la != lb for la, _, lb, _ in pairs)
        if similarity < .88 and not possible_translation:
            continue
        # Different floors/units are expected separate records, not under-merges.
        def locations(record, identity=identity):
            values = set()
            for c in record.fields[identity].candidates:
                for e in c.evidence:
                    if isinstance(e, VersionedEvidence):
                        index = indexes.get(e.document_id)
                        context = index.at(e.locator, e.quote) if index else e.structure_context
                        if context and any(context_signature(context)):
                            values.add(context_signature(context))
            return values
        ca, cb = locations(a), locations(b)
        structural_split = bool(ca and cb and ca != cb)
        if structural_split:
            # Different floors/units are expected separate records. The same name in
            # different sections ("Odalar" vs "Fiyatlar") with only complementary,
            # never disagreeing, values may be one thing split by WP114: list it.
            disagree = any(len(_groups(field, a.fields[field].candidates + b.fields[field].candidates)) > 1
                           for field in a.fields.keys() & b.fields.keys() if field != identity)
            if similarity < 1 or disagree:
                continue
        under.append({"collection": runtime.collections[a.type], "record_ids": [a.id, b.id],
                      "similarity": round(similarity, 4),
                      "reason": "same_name_different_structure" if structural_split else
                      "shared_translated_name" if any(la != lb and na == nb for la, na, lb, nb in pairs)
                      else "possible_translated_name" if possible_translation and similarity < .88
                      else "similar_name"})
    rejected = Counter(item.reason for result in results for item in result.rejected)
    return {"workspace_id": revision.workspace_id, "revision_id": revision.id,
            "records_per_collection": dict(sorted(counts.items())),
            "suspected_over_merges": over, "suspected_under_merges": under,
            "conflicts": {"real": real, "format_only": formatting},
            "rejected_fields_by_reason": dict(sorted(rejected.items())),
            "unsupported_fields": len(unsupported), "unsupported_field_details": unsupported,
            "missing_source_contexts": sorted({p.document_id for p in revision.documents} - contexts.keys())}


def markdown(report):
    lines = ["# Bilgi toparlama kalite raporu", "",
             f"Çalışma alanı: `{report['workspace_id']}` · Yayın: `{report['revision_id']}`", "",
             "| Bilgi listesi | Kayıt |", "| --- | ---: |"]
    lines.extend(f"| {key} | {count} |" for key, count in report["records_per_collection"].items())
    lines += ["", f"Gerçek çelişki: {len(report['conflicts']['real'])}",
              f"Yalnız yazım farkı: {len(report['conflicts']['format_only'])}",
              f"Kaynakla desteklenmeyen alan: {report['unsupported_fields']}", "",
              "## Fazla birleştirme şüphesi", ""]
    lines.extend(f"- `{s['record_id']}` / `{s['field']}`: `{s['document_id']}` "
                 f"({', '.join(s['locators'])}; {s['reason']})" for s in report["suspected_over_merges"])
    if not report["suspected_over_merges"]:
        lines.append("Yok.")
    lines += ["", "## Eksik birleştirme şüphesi", ""]
    lines.extend(f"- {' / '.join(s['record_ids'])}: {s['similarity']:.2f} ({s['reason']})"
                 for s in report["suspected_under_merges"])
    if not report["suspected_under_merges"]:
        lines.append("Yok.")
    lines += ["", "## Elenen alanlar", ""]
    lines.extend(f"- {reason}: {count}" for reason, count in report["rejected_fields_by_reason"].items())
    lines += ["", "Şüpheler inceleme içindir; rapor kayıtları birleştirmez ve çelişkileri çözmez.",
              ("Benzerlik TR/EN/DE/RU ad yazımlarını ve mevcut dil alternatiflerini kullanır; "
              "sözlük/model olmadan yazımı farklı saf çevirilerin anlamını kanıtlayamaz.")]
    if report["missing_source_contexts"]:
        lines += ["", "Kaynak bağlamı eksik: " + ", ".join(report["missing_source_contexts"])]
    return "\n".join(lines) + "\n"


def load_inputs(workspace, revision_path=None, records_path=None):
    if revision_path:
        revision = load_revision(Path(revision_path).read_bytes())
        if revision.workspace_id != workspace:
            raise ValueError("revision belongs to another workspace")
    else:
        from docgrain_api import records_jobs as lifecycle

        store = lifecycle.pack_store()
        head = lifecycle.head(store, workspace)
        if head is None:
            raise ValueError("workspace has no publication")
        revision = store._source(workspace, head)
        if records_path is None:
            # The head's own job first; older publications only as a fallback.
            for revision_id in [head, *store.list_revisions(workspace)]:
                job = store.manifest(workspace, revision_id).get("record_job_id")
                if job:
                    records_path = store._path(workspace) / "runtime" / sha256(job.encode()).hexdigest() / "records"
                    break
    if records_path is None:
        raise ValueError("records directory is required")
    results = load_records(records_path, runtime=revision_runtime(revision))
    contexts = {}
    for path in sorted(Path(records_path).rglob("records.json")):
        document_id = json.loads(path.read_text(encoding="utf-8"))["document_id"]
        context = path.parent / "context.md"
        if context.exists():
            contexts[document_id] = context.read_text(encoding="utf-8")
    return revision, results, contexts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--revision", help="offline merge_revision.json; default: live publication head")
    parser.add_argument("--records", help="job records directory; default: latest published job runtime")
    parser.add_argument("--out", required=True, help="private output filename prefix (outside Git)")
    args = parser.parse_args(argv)
    try:
        report = build_report(*load_inputs(args.workspace, args.revision, args.records))
        prefix = Path(args.out)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        prefix.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        prefix.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    except (ValueError, OSError) as exc:
        print(f"Rapor üretilemedi: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"Rapor hazır. Desteksiz alan: {report['unsupported_fields']}; "
          f"fazla/eksik birleştirme şüphesi: {len(report['suspected_over_merges'])}/"
          f"{len(report['suspected_under_merges'])}.")
    return 1 if report["unsupported_fields"] else 0


if __name__ == "__main__":
    sys.exit(main())
