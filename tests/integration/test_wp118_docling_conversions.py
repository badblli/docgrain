"""WP118 with the real Docling 2.130 (worker image): PDF heading levels, TXT via Markdown, header flags."""

import importlib.util
import json
import re
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from docgrain_domain.canonical import SourceVersion
from docgrain_domain.canonical.lifecycle import (
    processing_revision_id,
    source_revision_id,
)
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.canonical_mapper import CanonicalMapper
from docgrain_worker.canonical_writer import processing_spec
from docgrain_worker.structural import DocumentParser, VerifiedSource, _txt

pytestmark = pytest.mark.skipif(importlib.util.find_spec("docling") is None,
                                reason="Docling 2.130 worker image required")

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "structural"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import requests
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    def blocked(*args, **kwargs):
        pytest.fail("WP118 integration tests must not access the network")
    monkeypatch.setattr(requests.sessions.Session, "send", blocked)


def words(text: str) -> Counter:
    return Counter(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def parse(path: Path, fmt: SourceFormat):
    data = path.read_bytes()
    return DocumentParser().parse(VerifiedSource(path, sha256(data).hexdigest(), len(data)), fmt)


def canonical(path: Path, result):
    spec = processing_spec(result)
    digest = sha256(path.read_bytes()).hexdigest()
    source = SourceVersion(id=source_revision_id("ws", "doc", digest), document_id="doc", workspace_id="ws",
                           content_sha256=digest, storage_uri="fixture://source", storage_version="1",
                           byte_size=path.stat().st_size, mime_type="text/plain", filename=path.name,
                           recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
    return CanonicalMapper().map(result, source, revision_id=processing_revision_id(source.id, spec),
                                 created_at=source.recorded_at, processing=spec,
                                 pdf_path=path if result.source_format is SourceFormat.PDF else None)


def nested_heading_pdf(path: Path, *, bookmarks: bool) -> Path:
    import pymupdf
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    y = 80
    for text, size, font in (("1. Rooms", 18, "hebo"), ("1.1 Ground Floor", 14, "hebo"),
                             ("Garden room with terrace and two beds.", 11, "helv"),
                             ("1.2 Upper Floor", 14, "hebo"), ("Suite with private pool.", 11, "helv"),
                             ("2. Restaurants", 18, "hebo"), ("2.1 Main Restaurant", 14, "hebo"),
                             ("Open buffet from 07:00 to 22:00.", 11, "helv")):
        page.insert_text((60, y), text, fontsize=size, fontname=font)
        y += size + 22
    if bookmarks:
        pdf.set_toc([[1, "1. Rooms", 1], [2, "1.1 Ground Floor", 1], [2, "1.2 Upper Floor", 1],
                     [1, "2. Restaurants", 1], [2, "2.1 Main Restaurant", 1]])
    pdf.save(path)
    pdf.close()
    return path


@pytest.mark.parametrize("bookmarks", [True, False])
def test_pdf_nested_headings_get_levels_above_one(tmp_path, bookmarks):
    path = nested_heading_pdf(tmp_path / "headings.pdf", bookmarks=bookmarks)
    result = parse(path, SourceFormat.PDF)
    headings = [item for item in result.items if item.kind == "heading"]

    def level(title):
        # Docling's layout text may drop a leading outline number ("1. Rooms" -> "Rooms").
        return next(item.level for item in headings if item.text.endswith(title))

    assert result.processing_options["pipeline"]["heading_hierarchy_options"]["enabled"] is True
    assert result.reading_profile["version"] == "3"
    # Outline numbering alone ("2." / "2.1") already nests; which lines the layout model calls headings varies.
    assert level("Main Restaurant") > level("Restaurants")
    if not bookmarks:
        return
    assert level("Ground Floor") > level("Rooms") and level("Upper Floor") > level("Rooms")
    snapshot = canonical(path, result)
    sections = {n.heading.split(" ", 1)[-1] if n.heading[0].isdigit() else n.heading: n
                for n in snapshot.structure if n.kind == "section"}
    assert sections["Ground Floor"].id in sections["Rooms"].children


def test_txt_goes_through_docling_markdown_with_exact_text(tmp_path):
    path = tmp_path / "structured.txt"
    path.write_bytes((FIXTURES / "wp118-structured.txt").read_bytes())
    result = parse(path, SourceFormat.TXT)
    assert (result.parser, result.status) == ("docling", "complete")
    raw = json.loads(result.legacy_json)
    labels = Counter(t["label"] for t in raw["texts"])
    assert labels["section_header"] >= 3 and labels["list_item"] == 5
    text = path.read_bytes().decode("utf-8-sig")
    for item in result.items:
        assert text[item.locator["start"]:item.locator["end"]] == item.text
    assert [i.level for i in result.items if i.kind == "heading"] == [1, 2, 3, 3, 1]
    old = _txt(VerifiedSource(path, sha256(path.read_bytes()).hexdigest(), path.stat().st_size))
    old_words = words("\n".join(i.text for i in old.items))
    new_words = words("\n".join(i.text for i in result.items))
    assert sum((old_words & new_words).values()) == old_words.total()  # 100 % word recall
    snapshot = canonical(path, result)
    assert snapshot.schema_version == "0.6.0"
    table = next(n for n in snapshot.structure if n.kind == "table")
    assert [c.source_attributes for c in table.rows[0]] == [{"column_header": True}] * 3
    assert any(n.kind == "list" for n in snapshot.structure)
    from docgrain_records.structure_units import structure_units, unit_counts
    counts = unit_counts(structure_units(raw, "doc"))
    assert counts["table"] == 1 and counts["list"] >= 2


@pytest.mark.parametrize("name", ["odalar.txt", "hizmetler.txt"])
def test_plain_company_txt_keeps_every_word(tmp_path, name):
    source = Path(__file__).resolve().parents[1] / "fixtures" / "u1-company" / name
    path = tmp_path / name
    path.write_bytes(source.read_bytes())
    result = parse(path, SourceFormat.TXT)
    old = _txt(VerifiedSource(path, sha256(path.read_bytes()).hexdigest(), path.stat().st_size))
    assert result.parser == "docling"
    assert words("\n".join(i.text for i in result.items)) == words("\n".join(i.text for i in old.items))


def test_pdf_table_header_flags_reach_the_canonical_snapshot(tmp_path):
    from tests.fixtures.structural.docling_profiles import create_profile_corpus
    path = create_profile_corpus(tmp_path) / "synthetic" / "columns-table.pdf"
    result = parse(path, SourceFormat.PDF)
    raw = json.loads(result.legacy_json)
    flagged = [c for t in raw["tables"] for c in t["data"]["table_cells"] if c.get("column_header")]
    assert flagged, "TableFormer marked no column header in the synthetic table"
    snapshot = canonical(path, result)
    cells = [c for n in snapshot.structure if n.kind == "table" for row in n.rows for c in row]
    assert sum(bool((c.source_attributes or {}).get("column_header")) for c in cells) == len(flagged)
