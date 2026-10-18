"""WP123: OCR picture labels do not become identity boundaries; scanned floors do."""

import socket
from copy import deepcopy
from hashlib import sha256

import httpx
import pytest
from docgrain_api.records_repository import RecordsRepository
from docgrain_api.settings import get_settings
from docgrain_records.match import accept_strong_matches, load_records, propose_matches
from docgrain_records.match_merge import merge_matches
from docgrain_records.models import StructureContext, StructureHeading
from docgrain_records.structure_context import (
    StructureIndex,
    _labels,
    context_signature,
    contexts_conflict,
    normalized,
    pin_structure,
    record_contexts,
    structure_vocabulary,
    without_structure,
)
from docgrain_worker import republish

from tests.unit.test_structure_context import candidate, fact, save_result, verify


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("WP123 tests must not contact a network or model")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def node(key, kind, text="", *, children=(), page=1, origin=None, confidence=None):
    provenance = {"producer_id": "producer-synthetic" if origin else "producer-structural-parser",
                  "evidence_ids": [key], "confidence": confidence}
    if origin:
        provenance["confidence_method"] = "synthetic-recognition-min:" + origin
    result = {"id": key, "kind": kind, "children": list(children),
              "annotation": {"provenance": provenance}, "test_page": None if kind == "document" else page}
    if kind == "section":
        result["heading"] = text
    elif kind == "table":
        result["rows"] = [[{"value": text, "source_attributes": {"row_header": True}}]]
    elif text:
        result["text"] = text
    return result


def snapshot(nodes, doc="document-test"):
    result = {"document_id": doc, "workspace_id": "workspace-test",
              "knowledge_revision": {"id": "revision-structure"},
              "source_version": {"id": "version-test"}, "root_node_id": "root",
              "structure": deepcopy(nodes), "evidence": []}
    for item in result["structure"]:
        page = item.pop("test_page", None)
        result["evidence"].append({"id": item["id"], "locator": {"page_number": page}})
    return result


def compact(source):
    """Synthetic compact projection with the real canonical object aliases."""
    blocks, aliases = [], []
    for item in source["structure"]:
        if item["kind"] in {"document", "list"}:
            continue
        key = f"§{len(aliases) + 1}"
        body = ("# " + item["heading"] if item["kind"] == "section" else
                "| Oda |\n| --- |\n| " + item["rows"][0][0]["value"] + " |"
                if item["kind"] == "table" else item["text"])
        blocks.append(f"[{key} p.1]\n{body}\n")
        aliases.append(f"{key} → {item['id']}")
    return "\n".join(blocks) + "\n## Kaynak anahtarları\n" + "\n".join(aliases) + "\n"


@pytest.mark.parametrize("origin", ["ocr", "mixed"])
@pytest.mark.parametrize("native_kind", ["section", "text_block", "table"])
@pytest.mark.parametrize("page", [1, None])
def test_picture_heading_is_skipped_in_tree_paths(origin, native_kind, page):
    nodes = [node("root", "document", children=["floor", "native", "sibling"]),
             node("floor", "section", "Alt Kat", children=["logo"], page=page, origin="ocr"),
             node("logo", "section", "LOG şekil", children=["room"], page=page, origin=origin, confidence=.84),
             node("room", "text_block", "Hol", page=page, origin="ocr"),
             node("native", native_kind, "Doğal metin", page=page),
             node("sibling", "text_block", "Bağımsız", page=page, origin="ocr")]
    # A native ancestor stays structural; only the logo is OCR-derived here.
    nodes[1]["annotation"]["provenance"].pop("confidence_method")
    source = snapshot(nodes)
    index = StructureIndex(pin_structure(compact(source), source))
    assert [h.title for h in index.at("room").heading_path] == ["Alt Kat"]
    assert index.at("sibling").heading_path == []  # Canonical siblings do not adopt linear headings.
    assert all("LOG şekil" not in [h.title for h in c.heading_path] for c in index.contexts.values())
    assert "LOG şekil" in index.bodies[index.key("logo")]  # Evidence body is unchanged.


@pytest.mark.parametrize("native_kind", ["section", "text_block", "table"])
def test_native_text_signal_requires_the_same_page(native_kind):
    source = snapshot([node("root", "document", children=["floor", "native"]),
                       node("floor", "section", "Çatı Katı", children=["room"], origin="ocr", confidence=0),
                       node("room", "text_block", "Hol", origin="ocr"),
                       node("native", native_kind, "Doğal metin", page=2)])
    index = StructureIndex(pin_structure(compact(source), source))
    assert [h.title for h in index.at("room").heading_path] == ["Çatı Katı"]


@pytest.mark.parametrize("native_kind", ["section", "text_block", "table", "list"])
def test_each_native_text_kind_alone_identifies_picture_text(native_kind):
    native = (node("native", "list", children=["list-text"]) if native_kind == "list" else
              node("native", native_kind, "Doğal metin"))
    nodes = [node("root", "document", children=["logo", "native"]),
             node("logo", "section", "LOG şekil", children=["room"], origin="ocr"),
             node("room", "text_block", "Hol", origin="ocr"), native]
    if native_kind == "list":
        nodes.append(node("list-text", "text_block", "Doğal metin"))
    source = snapshot(nodes)
    index = StructureIndex(pin_structure(compact(source), source))
    assert index.at("room").heading_path == []


def test_empty_containers_and_pictures_are_not_native_text():
    source = snapshot([node("root", "document", children=["logo", "table", "list", "picture", "blank"]),
                       node("logo", "section", "Alt Kat", children=["room"], origin="ocr"),
                       node("room", "text_block", "Hol", origin="ocr"),
                       node("table", "table"), node("list", "list"), node("picture", "asset"),
                       node("blank", "text_block", " \n ")])
    source["structure"][3]["rows"] = []
    context = "[§1 p.1]\n# Alt Kat\n\n[§2 p.1]\nHol\n\n## Kaynak anahtarları\n§1 → logo\n§2 → room\n"
    index = StructureIndex(pin_structure(context, source))
    assert [h.title for h in index.at("room").heading_path] == ["Alt Kat"]


def floor_source(doc="document-test"):
    return snapshot([node("root", "document", children=["lower", "upper"]),
                     node("lower", "section", "Alt Kat", children=["room1"], origin="ocr", confidence=0),
                     node("room1", "text_block", "Hol; 32 m²", origin="ocr", confidence=.9),
                     node("upper", "section", "Çatı Katı", children=["room2"], origin="ocr", confidence=.97),
                     node("room2", "text_block", "Hol; 32 m²", origin="ocr", confidence=.9)], doc)


def rooms(source, *, old=False):
    if old:
        source = deepcopy(source)
        for item in source["structure"]:
            item["annotation"]["provenance"].pop("confidence_method", None)
    context = pin_structure(compact(source), source)
    index = StructureIndex(context)
    doc = source["document_id"]
    records = [candidate(name=[fact(item["text"].split(";")[0], index.key(item["id"]), doc=doc)],
                         size_m2=[fact(32, index.key(item["id"]), item["text"], doc=doc)])
               for item in source["structure"] if item["kind"] == "text_block"]
    result = verify(records, context, doc)
    assert not result.rejected
    return context, result


def test_fully_scanned_floor_headings_still_veto_merges(tmp_path):
    results = []
    for doc in ("scan-a", "scan-b"):
        context, result = rooms(floor_source(doc))
        assert len(result.records) == 2
        assert contexts_conflict(*result.records)
        save_result(tmp_path / "records", result, context)
        results.append(result)
    proposals = accept_strong_matches(results, propose_matches(results))
    assert sum(p.review_state == "accepted" for p in proposals.proposals) == 2
    assert sum(any(s.kind == "structure_conflict" for s in p.signals) for p in proposals.proposals) == 2
    merged = merge_matches(tmp_path / "records", results, proposals, tmp_path / "out")
    assert len(merged.records) == 2


def logo_sources():
    first = snapshot([node("root", "document", children=["floor"]),
                      node("floor", "section", "Alt Kat", children=["logo"]),
                      node("logo", "section", "LOG şekil", children=["room"], origin="ocr", confidence=.84),
                      node("room", "text_block", "Hol; 32 m²")], "document-a")
    second = snapshot([node("root", "document", children=["floor"]),
                       node("floor", "section", "Alt Kat", children=["room", "logo"]),
                       node("room", "text_block", "Hol; 32 m²"),
                       node("logo", "section", "LOG şekil", children=["other"]),
                       node("other", "text_block", "Salon; 32 m²")], "document-b")
    return first, second


def test_shared_vocabulary_picture_label_no_longer_splits_identical_names(tmp_path):
    results = []
    for source in logo_sources():
        context, result = rooms(source)
        save_result(tmp_path / "records", result, context)
        results.append(result)
    proposals = accept_strong_matches(results, propose_matches(results))
    same_name = [p for p in proposals.proposals if "hol" in p.left.source_identity and "hol" in p.right.source_identity]
    assert [p.review_state for p in same_name] == ["accepted"]
    assert not any(s.kind == "structure_conflict" for p in same_name for s in p.signals)
    merged = merge_matches(tmp_path / "records", results, proposals, tmp_path / "out")
    assert len(merged.records) == 2
    assert any(len(r.fields["name"].candidates[0].evidence) == 2 for r in merged.records)


@pytest.mark.parametrize("title", ["!!!", "№", "*", "—", "•", ""])
def test_junk_titles_are_not_identity_labels(title):
    _, result = rooms(floor_source())
    record = result.records[0]
    context = StructureContext(heading_path=[StructureHeading(locator="§1", title=title)] if title else [],
                               row_header=title, section_title=title)
    record.structure_context = [context]
    for evidence in record.name.evidence:
        evidence.structure_context = context
    assert context_signature(context) == ((), "", "")
    assert record_contexts(record) == []
    assert _labels(record) == set()
    assert structure_vocabulary([record]) == {result.document_id: set()}


@pytest.mark.parametrize("title", ["Alt Kat", "Çatı Katı", "ＡＢ", "ﬀ", "中文",
                                    "A", "B", "1", "2", "123", "Ａ", "Ç", "Ⓐ", "№ 1"])
def test_nfkc_letters_and_digits_are_structural(title):
    context = StructureContext(heading_path=[StructureHeading(locator="§1", title=title)],
                               row_header=title, section_title=title)
    assert context_signature(context) == ((normalized(title),), normalized(title), normalized(title))
    _, result = rooms(floor_source())
    record = result.records[0]
    record.structure_context = [context]
    assert _labels(record) == {normalized(title)}
    assert structure_vocabulary([record]) == {result.document_id: {normalized(title)}}


@pytest.mark.parametrize("unavailable", ["new-revision", "missing", "wrong-workspace", "wrong-source"])
def test_republish_refreshes_only_pinned_snapshot_on_a_copy(tmp_path, monkeypatch, unavailable):
    sources = logo_sources()
    store = RecordsRepository(tmp_path / "publications")
    workspace, job = "workspace-test", "synthetic-job"
    root = store._path(workspace) / "runtime" / sha256(job.encode()).hexdigest()
    results = []
    for source in sources:
        context, result = rooms(source, old=True)
        context += '§3 table={"row_header_column":99}\n'  # A stale WP118 pin must also be stripped.
        save_result(root / "records", result, context)
        results.append(result)
    # Old pins veto the accepted-name pair because both documents contain the logo title.
    old = merge_matches(root / "records", results, propose_matches(results), root / "old",
                        workspace, f"u1_{job}_wp115")
    assert len(old.records) == 3
    store.publish(old, job_id=job)
    before = {p.relative_to(root / "records"): p.read_bytes()
              for p in (root / "records").rglob("*") if p.is_file()}
    requested = []

    def handler(request):
        assert request.method == "GET"
        requested.append(request.url.path)
        source = deepcopy(next(s for s in sources if s["document_id"] in request.url.path))
        if source["document_id"] == "document-b":
            if unavailable == "missing":
                return httpx.Response(404)
            if unavailable == "new-revision":
                source["knowledge_revision"]["id"] = "newer-unpinned-revision"
            if unavailable == "wrong-workspace":
                source["workspace_id"] = "another-workspace"
            if unavailable == "wrong-source":
                source["source_version"]["id"] = "another-source"
        return httpx.Response(200, json={"snapshot": source})

    client_class = httpx.Client
    monkeypatch.setattr(republish.httpx, "Client", lambda **kw: client_class(
        **kw, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(get_settings(), "use_fixtures", False)
    monkeypatch.setattr(republish.jobs, "get", lambda *_: {"status": "done", "revision_id": old.id})
    monkeypatch.setattr(republish.lifecycle, "pack_store", lambda: store)
    monkeypatch.setattr(store, "stage", lambda *_: pytest.fail("dry run staged a publication"))
    monkeypatch.setattr(store, "publish", lambda *_: pytest.fail("dry run published"))
    report = republish.republish(workspace, dry_run=True)
    assert report["structure_pins_refreshed"] == "1 of 2 documents"
    assert report["published"] is False
    assert report["before"]["records"] == 3 and report["after"]["records"] == 2
    assert report["after"]["unsupported_fields"] == 0
    assert store.list_revisions(workspace) == [old.id]
    assert sorted(requested) == ["/v1/documents/document-a/knowledge", "/v1/documents/document-b/knowledge"]
    assert before == {p.relative_to(root / "records"): p.read_bytes()
                      for p in (root / "records").rglob("*") if p.is_file()}
    copy = root / "republish" / republish.RULES_VERSION / "records"
    refreshed = (copy / "document-a" / "context.md").read_text(encoding="utf-8")
    assert without_structure(refreshed) == without_structure(context_for(root, "document-a"))
    index = StructureIndex(refreshed)
    assert [h.title for h in index.at("room").heading_path] == ["Alt Kat"]
    assert refreshed.count("§3 structure=") == 1
    assert refreshed.count("§3 table=") == 0
    assert context_for(copy.parent, "document-b") == context_for(root, "document-b")
    loaded = load_records(copy)
    assert "LOG şekil" not in [h.title for r in loaded[0].records for c in r.structure_context for h in c.heading_path]
    retry = republish.republish(workspace, dry_run=True)
    assert retry["after"] == report["after"]


def context_for(root, doc):
    return (root / "records" / doc / "context.md").read_text(encoding="utf-8")
