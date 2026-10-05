"""Offline pinned-source audit; emits review evidence, never model/canonical/index writes."""

import argparse
import json
from pathlib import Path

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_worker.fidelity import audit_source

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot",type=Path,required=True)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--golden",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    snapshot = CanonicalKnowledgeSnapshot.model_validate_json(args.snapshot.read_bytes())
    golden = json.loads(args.golden.read_text(encoding="utf-8")) if args.golden else []
    result = audit_source(snapshot,args.source,golden_checks=golden)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"document_id":result["document_id"],"semantic_acceptance":result["semantic_acceptance"],
                      "golden_mismatches":sum(not c["matches"] for c in result["golden_table_checks"])}))
