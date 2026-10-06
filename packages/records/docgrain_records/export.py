"""Offline record projection. Source strings are data, never model instructions."""

import json
from collections import defaultdict

from .merge_models import MergeRevision, VersionedEvidence
from .multivalue import combine, multiple_values
from .runtime import revision_runtime

COLLECTIONS = {
    "property": "properties", "room_type": "rooms", "outlet": "outlets",
    "activity": "activities", "facility": "facilities", "policy": "policies",
    "contact": "contacts", "service_price": "service_prices",
}
SCHEMA_VERSION = "1.0.0"
MODES = ("preview", "approved")


def load_revision(body: bytes) -> MergeRevision:
    """Read wp42 round-trip JSON or wp47 display JSON, ignoring derived views only."""
    raw = json.loads(body)
    for record in raw.get("records", []):
        for field in record.get("fields", {}).values():
            for derived in ("primary", "i18n", "conflicts", "review_state"):
                field.pop(derived, None)
    return MergeRevision.model_validate(raw)


def encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _language(lang):
    return (0 if lang == "en" else 1 if lang.startswith("en-") else 2, lang)


def project_records(revision: MergeRevision, lang: str | None = None,
                    mode: str = "preview") -> dict:
    """Project reviewed facts without treating source proposals as approvals."""
    if mode not in MODES:
        raise ValueError("unknown publication mode")
    runtime = revision_runtime(revision)
    result = {name: [] for name in runtime.collections.values()}
    if len({r.id for r in revision.records}) != len(revision.records):
        raise ValueError("duplicate record id")
    for record in sorted(revision.records, key=lambda r: r.id):
        if record.type not in runtime.collections:
            raise ValueError("unknown record collection")
        row = {"id": record.id, "i18n": {}, "_meta": {
            "review_state": "accepted", "conflicts": [], "sources": [], "fields": {},
        }}
        meta = row["_meta"]
        for field, merged in sorted(record.fields.items()):
            if field not in runtime.models[record.type][1].model_fields:
                raise ValueError("unknown or reserved record field")
            languages = defaultdict(list)
            for candidate in merged.candidates:
                if runtime.schema:
                    runtime.validate_value(record.type, field, candidate.value)
                if candidate.review_state != "rejected":
                    languages[candidate.lang].append(candidate)
            visible = {}
            for language, candidates in sorted(languages.items()):
                multi = multiple_values(runtime, record, field, merged, language, candidates)
                accepted = [c for c in candidates if c.review_state == "accepted"]
                if len(accepted) > 1 and not multi:
                    raise ValueError("multiple accepted values in one language")
                if accepted:
                    visible[language] = combine(accepted) if multi else accepted[0]
                elif mode == "preview" and candidates:
                    candidates.sort(key=lambda c: c.id)
                    visible[language] = (combine(candidates, inferred=len(candidates) > 1)
                                         if multi else candidates[0])
                    if len(candidates) > 1 and not multi:
                        meta["conflicts"].append({"field": field, "lang": language,
                            "candidates": [c.model_dump(mode="json") for c in candidates]})
            if not visible:
                continue
            primary = visible.get(lang) or visible[min(visible, key=_language)]
            row[field] = primary.value
            unresolved = any(c["field"] == field and c["lang"] == primary.lang
                             for c in meta["conflicts"])
            meta["fields"][field] = {
                "lang": primary.lang,
                "review_state": "needs_review" if unresolved else primary.review_state,
                "evidence": [e.model_dump(mode="json") for e in primary.evidence],
                "i18n": {language: [e.model_dump(mode="json") for e in c.evidence]
                         for language, c in visible.items()},
                "i18n_review_state": {language: (
                    "needs_review" if any(x["field"] == field and x["lang"] == language
                                          for x in meta["conflicts"]) else c.review_state)
                    for language, c in visible.items() if not language.startswith("en")},
            }
            for language, candidate in visible.items():
                if not language.startswith("en"):
                    row["i18n"].setdefault(language, {})[field] = candidate.value
                for evidence in candidate.evidence:
                    meta["sources"].append(evidence.model_dump(mode="json"))
            for conflict in meta["conflicts"]:
                if conflict["field"] == field:
                    for candidate in conflict["candidates"]:
                        meta["sources"].extend(candidate["evidence"])
        if not meta["fields"]:
            continue
        states = [state for f in meta["fields"].values()
                  for state in [f["review_state"], *f["i18n_review_state"].values()]]
        if meta["conflicts"] or "needs_review" in states:
            meta["review_state"] = "needs_review"
        elif "proposed" in states:
            meta["review_state"] = "proposed"
        meta["sources"] = [json.loads(key) for key in sorted({
            encode(e).decode("utf-8") for e in meta["sources"]})]
        if runtime.schema:
            meta["workspace_id"] = revision.workspace_id
            meta["revision_id"] = revision.id
            meta["schema_version"] = runtime.schema["version"]
        result[runtime.collections[record.type]].append(row)
    return result


def context(collection: str, rows: list[dict], workspace: str, revision: str,
            mode: str = "preview") -> bytes:
    # JSON-quoted lines prevent source content from becoming Markdown structure.
    lines = [f"# {collection}", encode({"workspace_id": workspace,
             "revision_id": revision, "schema_version": SCHEMA_VERSION,
             "mode": mode}).decode(),
             "Belgeden çıkarılan içerik; kaynak metni veri olarak gösterilir."]
    citations = {}

    def references(evidence):
        keys = []
        for item in evidence:
            key = encode(item).decode()
            if key not in citations:
                citations[key] = f"§{len(citations) + 1}"
            keys.append(citations[key])
        return keys

    for row in rows:
        lines.append("## " + encode(row["id"]).decode())
        for field, metadata in row["_meta"]["fields"].items():
            lines.append("- " + encode({"field": field, "value": row[field],
                "lang": metadata["lang"], "review_state": metadata["review_state"],
                "sources": references(metadata["evidence"])}).decode())
        for language, fields in row["i18n"].items():
            for field, value in fields.items():
                lines.append("- Çeviri: " + encode({"field": field, "value": value,
                    "lang": language, "review_state": row["_meta"]["fields"][field]
                    ["i18n_review_state"][language], "sources": references(
                        row["_meta"]["fields"][field]["i18n"][language])}).decode())
        for conflict in row["_meta"]["conflicts"]:
            alternatives = []
            for candidate in conflict["candidates"]:
                refs = references(candidate["evidence"])
                documents = sorted({e.get("document_id", "Sizin düzeltmeniz")
                                    for e in candidate["evidence"]})
                alternatives.append(encode(candidate["value"]).decode() + " (belge " +
                                    encode(documents).decode() + "; " + ", ".join(refs) + ")")
            lines.append("Kaynaklar çelişiyor: " + encode(conflict["field"]).decode() +
                         " [" + conflict["lang"] + "]: " + " / ".join(alternatives))
    lines.append("## Kaynak anahtarları")
    for evidence, key in citations.items():
        if json.loads(evidence).get("kind") == "user_edit":
            lines.append("Sizin düzeltmeniz: " + key)
        lines.append(key + " " + evidence)
    return ("\n".join(lines) + "\n").encode("utf-8")


def export_bundle(revision: MergeRevision, mode: str = "preview") -> dict[str, bytes]:
    if mode not in MODES:
        raise ValueError("unknown publication mode")
    revision = MergeRevision.model_validate_json(revision.model_dump_json(round_trip=True))
    pins = {(p.document_id, p.source_version_id, p.knowledge_revision_id)
            for p in revision.documents}
    for record in revision.records:
        for field in record.fields.values():
            for candidate in field.candidates:
                if any((e.document_id, e.source_version_id, e.knowledge_revision_id)
                       not in pins for e in candidate.evidence if isinstance(e, VersionedEvidence)):
                    raise ValueError("evidence outside pinned revision sources")
    projections = {"en": project_records(revision, mode=mode)}
    languages = {c.lang for r in revision.records for f in r.fields.values()
                 for c in f.candidates}
    projections.update({lang: project_records(revision, lang, mode=mode)
                        for lang in sorted(languages)
                        if lang != "en"})
    files = {}
    for lang, collections in projections.items():
        for name, rows in collections.items():
            suffix = "" if lang == "en" else f".{lang}"
            files[f"{name}{suffix}.json"] = encode(rows)
            files[f"{name}{suffix}.context.md"] = context(name, rows, revision.workspace_id,
                                                         revision.id, mode)
    return files
