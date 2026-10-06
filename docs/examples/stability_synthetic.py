"""Generate four neutral workspaces offline; never read real company inputs."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from docgrain_eval.cli import main as evaluate
from docgrain_records.extractor import verify_response
from docgrain_records.match import propose_matches
from docgrain_records.match_merge import merge_matches, write_json
from docgrain_records.runtime import RuntimeRecords


def generate(root):
    workspaces = []
    for index, collection in enumerate(("rooms", "services", "classes", "products"), 1):
        workspace = f"synthetic_{index}"
        document = f"doc_{index}"
        context = "[§1 p.1]\n| Name | Amount |\n| --- | --- |\n| Garden | 20 |\n| River | 30 |\n"
        source = {"workspace_id": workspace, "document_id": document,
                  "source_version_id": "v1", "knowledge_revision_id": "k1",
                  "content_sha256": sha256(f"synthetic-source-{index}".encode()).hexdigest(), "lang": "en"}

        def fact(value, document=document):
            return {"value": value, "lang": "en", "evidence": [
                {"document_id": document, "locator": "§1", "quote": str(value)}]}

        schema = {"workspace_id": workspace, "version": 1, "review_state": "accepted", "sources": [],
                  "collections": [{"key": collection, "label_i18n": [{"lang": "en", "value": collection}],
                                   "description": "Synthetic list", "review_state": "accepted", "fields": [
                                       {"key": key, "type": kind, "unit": None, "review_state": "accepted",
                                        "label_i18n": [{"lang": "en", "value": key}]}
                                       for key, kind in (("name", "string"), ("amount", "integer"))],
                                   "examples": [{"values": [{"key": "name", **fact("Garden")}]}]}]}
        runtime = RuntimeRecords(schema)
        # Freeze source/schema before producing predictions. There are no accuracy keys.
        company = Path(root) / workspace
        for run_name in ("a", "b"):
            run = company / run_name
            extraction = run / "sources" / document
            write_json(extraction / "source.json", source)
            write_json(run / "schema.v1.json", schema)
            (extraction / "context.md").write_text(context, encoding="utf-8")
            response = {"records": [{"type": collection, "name": [fact(name)], "amount": [fact(amount)]}
                                    for name, amount in (("Garden", 20), ("River", 30))]}
            result = verify_response(json.dumps(response), context, document, "en", runtime=runtime)
            write_json(extraction / "records.json", result.model_dump(mode="json", exclude_none=True))
            revision = merge_matches(run / "sources", [result], propose_matches([result]), run / "merge")
            # Synthetic explicit approvals let the support command exercise published fields.
            for record in revision.records:
                for field in record.fields.values():
                    for candidate in field.candidates:
                        candidate.review_state = "accepted"
            write_json(run / "merge" / "merge_revision.json", revision.model_dump(mode="json"))
        write_json(Path(root) / "bundles" / f"{workspace}.json", {"workspace_id": workspace,
                   "files": [{"document_id": document, "version_id": "v1", "status": "done", "issues": []}]})
        workspaces.append(company / "a")
        assert evaluate(["stability", "--runs", str(company / "a"), str(company / "b"),
                         "--out", str(company / "stability")]) == 0
        assert evaluate(["support", "--revision", str(company / "a" / "merge" / "merge_revision.json"),
                         "--sources", str(company / "a" / "sources"),
                         "--out", str(company / "support.json")]) == 0
    assert evaluate(["companies", "--workspaces", *map(str, workspaces),
                     "--bundles", str(Path(root) / "bundles"),
                     "--out", str(Path(root) / "companies.md")]) == 0
    return workspaces


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    generate(parser.parse_args().out)
