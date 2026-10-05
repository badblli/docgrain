"""Run with python -m docgrain_records.merge_example; no network or real documents."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from .merge import JsonMergeStore, compare_revisions
from .merge_models import MergeDocument, SourceRecord
from .models import RoomType


def _document(document_id, lang, name, capacity, version):
    def fact(value, quote):
        return {"value": value, "lang": lang, "evidence": [{
            "document_id": document_id, "locator": "§1", "quote": quote,
        }]}

    return MergeDocument(
        workspace_id="workspace-example", document_id=document_id,
        source_version_id=f"{document_id}-v{version}",
        knowledge_revision_id=f"{document_id}-k{version}",
        context=f"[§1 p.1]\n{name}; capacity {capacity}\n",
        records=[SourceRecord(source_identity="room-a", aliases=["room-a"], record=RoomType(
            id="extractor-position:1", name=fact(name, name),
            capacity=fact(capacity, f"capacity {capacity}"),
        ))],
    )


def run_example(path: Path):
    store = JsonMergeStore(path, "workspace-example")
    tr = _document("doc_tr", "tr", "Bahçe odası", 2, 1)
    before = store.merge("merge-1", [_document("doc_en", "en", "Garden room", 2, 1), tr])
    # Only the EN capacity changes. The old TR fact remains an evidenced alternative.
    after = store.merge("merge-2", [tr, _document("doc_en", "en", "Garden room", 3, 2)])
    diff = compare_revisions(before, after)
    assert len(before.records) == len(after.records) == 1
    assert before.records[0].id == after.records[0].id
    assert [change.field for change in diff.fields if change.value_changed] == ["capacity"]
    assert [change.field for change in diff.fields if change.evidence_only] == ["name"]
    assert after.records[0].fields["name"].primary.lang == "en"
    assert after.records[0].fields["name"].i18n["tr"][0].evidence[0].document_id == "doc_tr"
    assert all(field.accepted() is None for field in after.records[0].fields.values())
    reopened = JsonMergeStore(path, "workspace-example")
    old = reopened.get_revision("merge-1")
    assert old.records[0].fields["capacity"].primary.value == 2
    print("Tek kayıt; İngilizce ana değer; Türkçe alanların kaynakları korundu.")
    print("Değer değişikliği: capacity. Yalnız kaynak değişikliği: name.")
    print("Eski düzenleme geçmişi yeniden açıldı; önceki kapasite: 2.")
    return diff


def main():
    parser = argparse.ArgumentParser(description="Çevrimdışı, sentetik kayıt birleştirme örneği")
    parser.add_argument("--store", type=Path, help="Kimlik ve geçmiş dosyasının yolu")
    args = parser.parse_args()
    if args.store:
        run_example(args.store)
    else:
        with TemporaryDirectory(prefix="docgrain-merge-") as directory:
            run_example(Path(directory) / "merge.json")


if __name__ == "__main__":
    main()
