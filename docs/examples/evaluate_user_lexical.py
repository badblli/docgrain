"""Read-only lexical/reranking benchmark labeled from canonical XLSX row evidence."""

import argparse
import json
from pathlib import Path

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.chunking import ChunkingSpec
from docgrain_domain.canonical.evaluation import GoldenQuery, evaluate

from tests.fixtures.incremental import index_spec
from tests.fixtures.retrieval import view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    snapshot = CanonicalKnowledgeSnapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
    prepared = view(snapshot, spec=index_spec(chunking=ChunkingSpec(max_table_rows=1)))
    table = max((n for n in snapshot.structure if n.kind == "table"), key=lambda n: len(n.rows))
    golden = []
    for term in ("kahvaltı", "dondurma", "fitness"):
        rows = [i for i, row in enumerate(table.rows) if any(term in str(c.value).casefold() for c in row)]
        if not rows:
            continue
        expected = {snapshot.document_id + ":" + entry.chunk.object_ref.object_id: 1
                    for entry in prepared.generation.entries if any(s.object_ref.object_id == table.id and s.start in rows
                                                                  for s in entry.chunk.sources)}
        if not expected:
            raise ValueError("golden row evidence missing from prepared chunks")
        golden.append(GoldenQuery(id=term, text=term, label_kind="object", relevance=expected))
    golden.append(GoldenQuery(id="none", text="absent_needle_12345", label_kind="object", relevance={}))
    report = evaluate([prepared], golden, {"lexical": {"mode": "lexical"}, "lexical-rerank": {"mode": "lexical", "reranking": {}}},
                      workspace_id=snapshot.workspace_id, document_ids=[snapshot.document_id], k=5)
    report["scope"] = "Real canonical XLSX row labels; lexical/reranker only. Synthetic generation vectors are not searched or persisted."
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: row["mean"] for name, row in report["strategies"].items()}))


if __name__ == "__main__":
    main()
