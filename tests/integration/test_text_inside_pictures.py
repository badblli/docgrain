"""WP107: designed pages (text layer over a full-page picture) keep their words; worker image only."""

import importlib.util
import json
from hashlib import sha256

import pytest
from docgrain_domain.source_format import SourceFormat
from docgrain_worker.structural import DocumentParser, VerifiedSource

from benchmarks.docling_profiles import measure
from tests.fixtures.structural.picture_text import text_over_picture_pdf

pytestmark = pytest.mark.skipif(importlib.util.find_spec("docling") is None,
                                reason="Docling 2.130 worker image required")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import requests
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    def blocked(*args, **kwargs):
        pytest.fail("integration tests must not access the network")
    monkeypatch.setattr(requests.sessions.Session, "send", blocked)


@pytest.mark.parametrize("dotted", [True, False])
def test_text_over_background_picture_keeps_words_with_bbox(tmp_path, dotted):
    path = text_over_picture_pdf(tmp_path / f"menu-{dotted}.pdf", dotted=dotted)
    row = measure(path, "C_tesseract")
    assert row["status"] != "failed"
    assert row["word_recall"] >= 0.95
    assert row["bbox_total"] >= 1 and row["bbox_resolved"] == row["bbox_total"]


def test_dotted_price_list_is_a_document_index_table_and_is_kept(tmp_path):
    """Pinned Docling labels this list `document_index`; it used to be dropped as a text-less paragraph."""
    path = text_over_picture_pdf(tmp_path / "menu.pdf")
    data = path.read_bytes()
    result = DocumentParser().parse(VerifiedSource(path, sha256(data).hexdigest(), len(data)), SourceFormat.PDF)
    raw = json.loads(result.legacy_json)
    assert any(table.get("label") == "document_index" for table in raw.get("tables", []))
    tables = [item for item in result.items if item.kind == "table"]
    values = " ".join(str(cell.get("value") or "") for table in tables for row in table.cells for cell in row)
    assert "Chocolate Cake" in values and "Sparkling Water" in values
