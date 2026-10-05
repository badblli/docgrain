"""Reproducible offline comparison; controlled vectors are explicitly test-only."""

import argparse
import json
from pathlib import Path

from docgrain_domain.canonical.evaluation import GoldenQuery, evaluate

from tests.fixtures.retrieval import view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    fixture = view(vector_for=lambda c: [0.0, 1.0] if "Beta" in c.retrieval_text else [1.0, 0.0])
    root = Path(__file__).resolve().parents[2]
    dataset = json.loads((root / "tests/fixtures/retrieval-golden-1.json").read_text(encoding="utf-8"))
    identities = {n.identity_key: n.id for n in fixture.snapshot.structure}
    golden = []
    for query in dataset["queries"]:
        expected = {"document-test:" + c.chunk.object_ref.object_id: query["grade"]
                    for c in fixture.generation.entries if any(s.object_ref.object_id == identities.get(query["source_identity_key"])
                                                               for s in c.chunk.sources)}
        if query["source_identity_key"] is not None and not expected:
            raise ValueError("golden source anchor disappeared from prepared corpus")
        golden.append(GoldenQuery(id=query["id"], text=query["text"], label_kind="object", relevance=expected))
    query_vector = {"spec": fixture.generation.spec.embedding.model_dump(mode="json"), "vector": [0.0, 1.0]}
    strategies = {"lexical": {"mode": "lexical"}, "vector": {"mode": "vector", "query_embedding": query_vector},
                  "hybrid": {"mode": "hybrid", "query_embedding": query_vector},
                  "lexical-rerank": {"mode": "lexical", "reranking": {}}}
    report = evaluate([fixture], golden, strategies, workspace_id="workspace-test", document_ids=["document-test"], k=3)
    report["dataset"] = dataset
    report["scope"] = "Synthetic ranking correctness benchmark; dense vectors are not semantic model output."
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: row["mean"] for name, row in report["strategies"].items()}))


if __name__ == "__main__":
    main()
