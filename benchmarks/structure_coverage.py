"""WP117 structure coverage: how much of a company's data Docling's structures already give us.

Read-only measurement (decision 21). For each workspace it loads every document's stored
DoclingDocument JSON, lists structural units (tables, lists, key-value areas, sheets), groups them
deterministically into candidate collections and compares them with the workspace's current
published, model-based revision. No model call and no write to the stack.

Where the Docling JSON comes from (live mode, first that works per document):

1. ``GET /v1/documents/{id}/knowledge`` -> canonical snapshot. ``metadata.docling_document`` when the
   worker kept it inline; otherwise the artifact with role ``docling-document`` whose ``storage_uri``
   (``s3://<bucket>/artifacts/<doc>/<version>/structural/docling/<sha256>.json?versionId=…``) is read
   from MinIO and checked against its SHA-256. MinIO credentials come from ``S3_ACCESS_KEY`` /
   ``S3_SECRET_KEY`` in the environment or the ``--env-file`` (default: the repository ``.env``).
2. ``GET /v1/documents/{id}/versions/{version}/artifacts/document.json`` (PDFs only) when MinIO is
   not reachable.

Output (private, contains file names and company text): ``<out>/structure-coverage.json`` and
``<out>/structure-coverage.md``; ``data/`` is git-ignored.

    python benchmarks/structure_coverage.py                       # all workspaces, live API
    python benchmarks/structure_coverage.py --workspace ws_… --workspace ws_…
    python benchmarks/structure_coverage.py --fixtures tests/fixtures/structure   # dry run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
for package in ("packages/evaluation", "packages/domain", "packages/records"):
    sys.path.insert(0, str(ROOT / package))

from docgrain_records.normalize import fold
from docgrain_records.structure_units import (
    Grouping,
    StructureUnit,
    group_units,
    norm,
    structure_units,
    unit_counts,
)

_RECORD_KEYS = {"_meta", "i18n", "id", "name"}
MIN_SHARED = 2


# --------------------------------------------------------------------------- pure measurement


def _scalars(value) -> list[str]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float, str)):
        return [str(value)] if str(value).strip() else []
    if isinstance(value, list):
        return [text for item in value for text in _scalars(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _scalars(item)]
    return []


def record_names(record: dict) -> set[str]:
    names = {norm(record.get("name"))}
    for translation in (record.get("i18n") or {}).values():
        if isinstance(translation, dict):
            names.add(norm(translation.get("name")))
    return names - {""}


def record_values(record: dict) -> list[tuple[str, str]]:
    return [(key, text) for key, value in record.items() if key not in _RECORD_KEYS
            for text in _scalars(value)]


class _Cells:
    """Folded structure texts (item names and values) for containment checks."""

    def __init__(self, units: list[StructureUnit]):
        texts = set()
        for unit in units:
            for item in unit.items:
                for text in [item.name or "", *item.values.values()]:
                    folded = fold(text) if text else ""
                    if folded:
                        texts.add(folded)
        self.exact = texts
        self.joined = " " + "  ".join(sorted(texts)) + " "

    def contains(self, text: str) -> bool:
        needle = fold(text) if text else ""
        return bool(needle) and (needle in self.exact or f" {needle} " in self.joined)


def map_collections(grouping: Grouping, published: dict[str, dict]) -> dict[str, list[str]]:
    """Published collection key -> candidate collection ids of the same kind of list.

    A candidate maps to every published collection that shares record names with it (at least
    two, or one when that is half of the candidate's records) or whose key/label equals one of its
    names after normalization. The model may split one kind of list in two (e.g. restaurants and
    food services naming the same outlets), so one candidate can be similar to both.
    """
    names = {key: set().union(*(record_names(r) for r in entry["records"])) if entry["records"]
             else set() for key, entry in published.items()}
    labels = {key: {norm(key.replace("_", " ")), norm(entry.get("label"))} - {""}
              for key, entry in published.items()}
    mapping: dict[str, list[str]] = {key: [] for key in published}
    for collection in grouping.collections:
        keys = {record.key for record in collection.records}
        own_names = {norm(name) for name in collection.names}
        for key in sorted(published):
            shared = len(keys & names[key])
            named = bool(own_names & labels[key])
            if shared >= MIN_SHARED or (shared and shared / len(keys) >= 0.5) or named:
                mapping[key].append(collection.id)
    return mapping


def _share(hit: int, total: int) -> float | None:
    return round(hit / total, 4) if total else None


def compare(units: list[StructureUnit], grouping: Grouping, published: dict[str, dict]) -> dict:
    """Published (model-based) records vs structure-only candidates of the same workspace."""
    by_id = {collection.id: collection for collection in grouping.collections}
    unit_by_id = {unit.id: unit for unit in units}
    mapping = map_collections(grouping, published)
    any_items = {record.key for c in grouping.collections for record in c.records}
    any_cells = _Cells(units)
    rows = []
    totals = Counter()
    for key in sorted(published):
        entry = published[key]
        matched = [by_id[cid] for cid in mapping[key]]
        matched_keys = {record.key for c in matched for record in c.records}
        matched_cells = _Cells([unit_by_id[uid] for c in matched for uid in c.units])
        counts = Counter()
        for record in entry["records"]:
            names = record_names(record)
            counts["records"] += 1
            counts["name_matched"] += bool(names & matched_keys)
            counts["name_any_item"] += bool(names & any_items)
            counts["name_any_cell"] += any(any_cells.contains(n) for n in names)
            for _, value in record_values(record):
                counts["values"] += 1
                counts["value_matched"] += matched_cells.contains(value)
                counts["value_any_cell"] += any_cells.contains(value)
        totals.update(counts)
        rows.append({
            "collection": key, "label": entry.get("label"), "records": counts["records"],
            "candidates": [{"id": c.id, "name": c.name, "records": len(c.records)} for c in matched],
            "record_name_share": _share(counts["name_matched"], counts["records"]),
            "record_name_any_item_share": _share(counts["name_any_item"], counts["records"]),
            "value_share": _share(counts["value_matched"], counts["values"]),
            "value_any_cell_share": _share(counts["value_any_cell"], counts["values"]),
            "values": counts["values"],
        })
    mapped = {cid for ids in mapping.values() for cid in ids}
    structure_only = [c for c in grouping.collections
                      if c.id not in mapped and (c.records or c.fields)]
    return {
        "published_records": totals["records"],
        "published_values": totals["values"],
        "record_name_share": _share(totals["name_matched"], totals["records"]),
        "record_name_any_item_share": _share(totals["name_any_item"], totals["records"]),
        "record_name_any_cell_share": _share(totals["name_any_cell"], totals["records"]),
        "value_share": _share(totals["value_matched"], totals["values"]),
        "value_any_cell_share": _share(totals["value_any_cell"], totals["values"]),
        "counts": dict(totals),
        "collections": rows,
        "published_only": [key for key in sorted(published) if not mapping[key]],
        "structure_only": [{"id": c.id, "name": c.name, "records": len(c.records),
                            "fields": c.fields[:12]} for c in structure_only],
    }


def measure_workspace(documents: list[dict], published: dict[str, dict] | None, *,
                      full: bool = False) -> dict:
    """``documents``: [{id, filename, mime_type, docling (dict|None), source}] of one workspace."""
    units: list[StructureUnit] = []
    rows = []
    for document in documents:
        found = structure_units(document["docling"], document["id"]) if document.get("docling") else []
        units.extend(found)
        rows.append({key: document.get(key) for key in ("id", "filename", "mime_type", "source")}
                    | {"units": unit_counts(found)})
    grouping = group_units(units)
    collections = []
    for c in grouping.collections:
        collections.append({
            "id": c.id, "name": c.name, "names": c.names[:5], "kinds": c.kinds,
            "units": len(c.units), "documents": len(c.documents), "fields": c.fields,
            "records": len(c.records), "multi_document_records": sum(len(r.documents) > 1
                                                                     for r in c.records),
            "records_with_conflicts": sum(bool(r.conflicts) for r in c.records),
            "unnamed_items": c.unnamed_items, "joined_by": c.joined_by,
            "record_names": [r.name for r in c.records][:50],
        })
    result = {
        "documents": rows,
        "documents_with_docling": sum(bool(d.get("docling")) for d in documents),
        "units": unit_counts(units),
        "items": sum(len(u.items) for u in units),
        "candidate_collections": len(grouping.collections),
        "candidate_collections_2plus_records": sum(len(c.records) >= 2 for c in grouping.collections),
        "candidate_records": sum(len(c.records) for c in grouping.collections),
        "collections": collections,
        "ambiguous": [asdict(a) for a in grouping.ambiguous],
        "comparison": compare(units, grouping, published) if published is not None else None,
    }
    if full:
        result["unit_detail"] = [unit.to_dict() for unit in units]
        result["grouping_detail"] = grouping.to_dict()
    return result


def summarize(workspaces: list[dict]) -> dict:
    totals = Counter()
    for ws in workspaces:
        totals["documents"] += len(ws["documents"])
        totals["documents_with_docling"] += ws["documents_with_docling"]
        totals.update({f"units_{k}": v for k, v in ws["units"].items()})
        totals["candidate_collections"] += ws["candidate_collections"]
        totals["candidate_records"] += ws["candidate_records"]
        comparison = ws.get("comparison") or {}
        totals.update(comparison.get("counts", {}))
        totals["published_collections"] += len(comparison.get("collections", []))
        totals["published_only"] += len(comparison.get("published_only", []))
        totals["structure_only"] += len(comparison.get("structure_only", []))
    return dict(totals) | {
        "record_name_share": _share(totals["name_matched"], totals["records"]),
        "record_name_any_item_share": _share(totals["name_any_item"], totals["records"]),
        "value_share": _share(totals["value_matched"], totals["values"]),
        "value_any_cell_share": _share(totals["value_any_cell"], totals["values"]),
    }


def _pct(value) -> str:
    return "–" if value is None else f"{value * 100:.1f}%"


def render_markdown(report: dict) -> str:
    lines = ["# Structure coverage (WP117)", "",
             (f"Generated {report['generated_at']} · source `{report['source']}` · mode "
              f"`{report['mode']}`. Private: contains document names and text."), "",
             ("| Workspace | Docs (Docling) | Tables | Lists | KV | Sheets | Candidate collections "
              "(≥2 rec) | Candidate records | Published records | Name in matched | Name anywhere "
              "| Values in matched | Values anywhere | Published only | Structure only |"),
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for ws in report["workspaces"]:
        c = ws.get("comparison") or {}
        u = ws["units"]
        lines.append(
            f"| {ws['name']} | {len(ws['documents'])} ({ws['documents_with_docling']}) | "
            f"{u['table']} | {u['list']} | {u['key_value']} | {u['sheet']} | "
            f"{ws['candidate_collections']} ({ws['candidate_collections_2plus_records']}) | "
            f"{ws['candidate_records']} | {c.get('published_records', '–')} | "
            f"{_pct(c.get('record_name_share'))} | {_pct(c.get('record_name_any_item_share'))} | "
            f"{_pct(c.get('value_share'))} | {_pct(c.get('value_any_cell_share'))} | "
            f"{len(c.get('published_only', []))} | {len(c.get('structure_only', []))} |")
    t = report["totals"]
    lines += ["", (f"**All:** {t.get('documents', 0)} documents "
                   f"({t.get('documents_with_docling', 0)} with Docling JSON), "
                   f"{t.get('candidate_collections', 0)} candidate collections, "
                   f"{t.get('candidate_records', 0)} candidate records; published records "
                   f"{t.get('records', 0)} — name found in matched structure "
                   f"{_pct(t.get('record_name_share'))}, anywhere "
                   f"{_pct(t.get('record_name_any_item_share'))}; published values in matched "
                   f"structure {_pct(t.get('value_share'))}, anywhere "
                   f"{_pct(t.get('value_any_cell_share'))}."), ""]
    for ws in report["workspaces"]:
        lines += [f"## {ws['name']} (`{ws['workspace_id']}`)", ""]
        if ws.get("error"):
            lines += [f"Error: {ws['error']}", ""]
            continue
        c = ws.get("comparison")
        if c:
            lines += ["| Published collection | Records | Candidates | Name share | Value share |",
                      "|---|---|---|---|---|"]
            for row in c["collections"]:
                names = ", ".join(f"{x['name']} ({x['records']})" for x in row["candidates"]) or "—"
                lines.append(f"| {row['collection']} | {row['records']} | {names} | "
                             f"{_pct(row['record_name_share'])} | {_pct(row['value_share'])} |")
            lines.append("")
        lines += ["Candidate collections (top 15 by records):", ""]
        for col in ws["collections"][:15]:
            fields = ", ".join(col["fields"][:8])
            lines.append(f"- **{col['name'] or '(no name)'}** — {col['records']} records, "
                         f"{col['units']} units in {col['documents']} documents ({'/'.join(col['kinds'])}); "
                         f"fields: {fields or '—'}")
        lines += ["", f"Ambiguous joins: {len(ws['ambiguous'])}", ""]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- sources


def _env(path: Path | None) -> dict[str, str]:
    values = {}
    if path and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values | {k: v for k, v in os.environ.items() if k.startswith("S3_")}


class LiveSource:
    """Read-only HTTP (and MinIO) access. Only GET requests and object reads."""

    def __init__(self, api: str, s3_endpoint: str | None, env: dict[str, str], timeout: float = 120):
        import httpx

        self.http = httpx.Client(base_url=api.rstrip("/"), timeout=timeout)
        self.api = api
        self.minio = None
        if s3_endpoint and env.get("S3_ACCESS_KEY") and env.get("S3_SECRET_KEY"):
            from minio import Minio

            parsed = urlparse(s3_endpoint)
            self.minio = Minio(parsed.netloc or parsed.path, access_key=env["S3_ACCESS_KEY"],
                               secret_key=env["S3_SECRET_KEY"], secure=parsed.scheme == "https")

    def get(self, path: str, **params):
        response = self.http.get(path, params=params or None)
        response.raise_for_status()
        return response.json()

    def workspaces(self) -> list[dict]:
        return self.get("/v1/workspaces")

    def documents(self, workspace_id: str) -> list[dict]:
        return self.get("/v1/documents", workspace_id=workspace_id, limit=10000)

    def docling(self, item: dict) -> tuple[dict | None, str]:
        document = item["document"]
        try:
            snapshot = self.get(f"/v1/documents/{document['id']}/knowledge")["snapshot"]
        except Exception:  # noqa: BLE001 - measurement: record why, keep going
            snapshot = None
        if snapshot:
            inline = (snapshot.get("metadata") or {}).get("docling_document")
            if inline:
                return inline, "snapshot_inline"
            artifact = next((a for a in snapshot.get("artifacts") or []
                             if a.get("role") == "docling-document"), None)
            if artifact and self.minio:
                data = self._object(artifact["storage_uri"])
                if data is not None and sha256(data).hexdigest() == artifact.get("content_sha256"):
                    return json.loads(data), "minio_artifact"
        version = item.get("latest_version") or {}
        if version.get("id"):
            response = self.http.get(f"/v1/documents/{document['id']}/versions/{version['id']}"
                                     "/artifacts/document.json")
            if response.status_code == 200:
                return response.json(), "api_pdf_artifact"
        parser = ((snapshot or {}).get("metadata") or {}).get("structural_parse", {}).get("parser")
        # e.g. TXT is read by our deterministic text parser: there is no Docling structure.
        return None, f"missing:{parser}" if parser else "missing"

    def _object(self, uri: str) -> bytes | None:
        parsed = urlparse(uri)
        if parsed.scheme != "s3":
            return None
        version = (parse_qs(parsed.query).get("versionId") or [None])[0]
        try:
            response = self.minio.get_object(parsed.netloc, parsed.path.lstrip("/"),
                                             version_id=version)
        except Exception:  # noqa: BLE001
            return None
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def published(self, workspace_id: str, mode: str) -> tuple[str | None, dict | None]:
        try:
            summary = self.get(f"/v1/workspaces/{workspace_id}/summary")
        except Exception:  # noqa: BLE001 - no publication yet
            return None, None
        revision = summary["revision_id"]
        labels = {c["key"]: c.get("label") for c in summary.get("collections") or []}
        base = f"/v1/workspaces/{workspace_id}/revisions/{revision}/collections"
        keys = self.get(base, mode=mode).get("collections") or []
        result = {}
        for key in keys:
            key = key if isinstance(key, str) else key.get("key")
            result[key] = {"label": labels.get(key), "records": self.get(f"{base}/{key}", mode=mode)}
        return revision, result


def load_fixtures(directory: Path) -> tuple[list[dict], dict | None]:
    documents = []
    for path in sorted(directory.glob("*.json")):
        if path.name == "published.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_name") == "DoclingDocument":
            documents.append({"id": path.stem, "filename": path.name, "mime_type": None,
                              "docling": data, "source": "fixture"})
    published_path = directory / "published.json"
    published = (json.loads(published_path.read_text(encoding="utf-8"))
                 if published_path.is_file() else None)
    return documents, published


def run(args) -> dict:
    started = datetime.now(UTC).isoformat()
    workspaces = []
    if args.fixtures:
        documents, published = load_fixtures(args.fixtures)
        result = measure_workspace(documents, published, full=args.full)
        workspaces.append({"workspace_id": "fixtures", "name": args.fixtures.name,
                           "revision_id": None} | result)
        source = f"fixtures:{args.fixtures.as_posix()}"
    else:
        live = LiveSource(args.api, None if args.no_minio else args.s3_endpoint, _env(args.env_file))
        listed = live.workspaces()
        wanted = set(args.workspace or [])
        for ws in listed:
            if wanted and ws["id"] not in wanted:
                continue
            clock = time.perf_counter()
            entry = {"workspace_id": ws["id"], "name": ws.get("name")}
            try:
                documents = []
                for item in live.documents(ws["id"]):
                    docling, origin = live.docling(item)
                    document = item["document"]
                    documents.append({"id": document["id"], "filename": document.get("filename"),
                                      "mime_type": document.get("mime_type"), "docling": docling,
                                      "source": origin})
                revision, published = live.published(ws["id"], args.mode)
                entry |= {"revision_id": revision} | measure_workspace(documents, published,
                                                                       full=args.full)
            except Exception as exc:  # noqa: BLE001 - one workspace must not stop the run
                entry |= {"error": f"{type(exc).__name__}: {exc}", "documents": [],
                          "documents_with_docling": 0, "units": unit_counts([]),
                          "candidate_collections": 0, "candidate_collections_2plus_records": 0,
                          "candidate_records": 0, "collections": [], "ambiguous": [],
                          "comparison": None}
            entry["seconds"] = round(time.perf_counter() - clock, 2)
            workspaces.append(entry)
            print(f"{ws['id']}: {len(entry['documents'])} documents, "
                  f"{entry['candidate_collections']} candidate collections", file=sys.stderr)
        source = args.api
    return {"generated_at": started, "source": source, "mode": args.mode,
            "workspaces": workspaces, "totals": summarize(workspaces)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=os.environ.get("DOCGRAIN_API", "http://localhost:8000"))
    parser.add_argument("--workspace", action="append", help="workspace id (repeatable; default all)")
    parser.add_argument("--mode", default="approved", help="publication mode for the comparison")
    parser.add_argument("--out", type=Path, default=ROOT / "data/benchmarks/structure-coverage",
                        help="private output directory (JSON + Markdown)")
    parser.add_argument("--s3-endpoint", default=os.environ.get("S3_PUBLIC_ENDPOINT_URL",
                                                                "http://localhost:9000"))
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env",
                        help="read S3_ACCESS_KEY / S3_SECRET_KEY from this file if present")
    parser.add_argument("--no-minio", action="store_true",
                        help="only use the API (PDF document.json); non-PDF documents are skipped")
    parser.add_argument("--fixtures", type=Path,
                        help="dry run: DoclingDocument JSON files (+ optional published.json)")
    parser.add_argument("--full", action="store_true", help="also write every unit with evidence")
    args = parser.parse_args(argv)
    report = run(args)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "structure-coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.out / "structure-coverage.md").write_text(render_markdown(report), encoding="utf-8")
    totals = report["totals"]
    print(json.dumps({key: totals.get(key) for key in (
        "documents", "documents_with_docling", "candidate_collections", "candidate_records",
        "records", "record_name_share", "record_name_any_item_share", "value_share",
        "value_any_cell_share")}, ensure_ascii=False))
    print(f"wrote {args.out / 'structure-coverage.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
