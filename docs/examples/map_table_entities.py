"""Preview explicit table mappings without DB writes, re-ingestion or model calls."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from docgrain_api.entity_service import EntityBatch
from docgrain_api.table_entities import ColumnBinding, table_candidates
from docgrain_domain.canonical import (
    CanonicalKnowledgeSnapshot,
    DomainSchemaRef,
    Producer,
    SchemaEntity,
    canonical_json_bytes,
    entity_id,
)
from docgrain_domain.canonical.entities import RegisteredSchema, validate_entity_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("schema", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--schema-id", required=True)
    parser.add_argument("--schema-version", default="1")
    parser.add_argument("--entity-type", required=True)
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--identity-field", required=True)
    parser.add_argument("--field", action="append", required=True, help="name=zero-based-column")
    parser.add_argument("--skip-rows", type=int, default=1)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    snapshot = CanonicalKnowledgeSnapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
    document = json.loads(args.schema.read_text(encoding="utf-8"))
    schema = RegisteredSchema(workspace_id=snapshot.workspace_id, document=document, reference=DomainSchemaRef(
        id=args.schema_id, version=args.schema_version, content_sha256=sha256(canonical_json_bytes(document)).hexdigest()))
    table = next(node for node in snapshot.structure if node.id == args.table_id and node.kind == "table")
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        table = table.model_copy(update={"rows": table.rows[:args.skip_rows + args.limit]})
    view = snapshot.model_copy(update={"structure": [table if node.id == table.id else node for node in snapshot.structure]})
    bindings = {}
    for field in args.field:
        name, column = field.rsplit("=", 1)
        if name in bindings:
            parser.error("duplicate field binding")
        bindings[name] = ColumnBinding(int(column))
    producer = Producer(id="producer-explicit-table-mapping", name="explicit-table-mapping", version="1")
    candidates = table_candidates(view, table.id, bindings=bindings, identity_field=args.identity_field,
                                  entity_type=args.entity_type, producer=producer, skip_rows=args.skip_rows)
    batch = EntityBatch(schema_ref=schema.reference, producer=producer, entities=candidates)
    entities = [SchemaEntity(id=entity_id(snapshot.document_id, schema.reference.id, item.identity_key),
                             schema_id=schema.reference.id, schema_version=schema.reference.version,
                             validation=validate_entity_data(item.data, schema), **item.model_dump()) for item in candidates]
    refs = {ref for entity in entities for annotation in entity.field_annotations.values()
            for ref in annotation.provenance.evidence_ids}
    payload = {"mode": "preview-only", "base_revision_id": snapshot.knowledge_revision.id,
               "source_version": snapshot.source_version.model_dump(mode="json"), "table_id": table.id,
               "mapping": {"fields": {name: binding.column for name, binding in bindings.items()},
                           "skip_rows": args.skip_rows, "limit": args.limit},
               "registered_schema": schema.model_dump(mode="json"), "batch": batch.model_dump(mode="json"),
               "entities": [item.model_dump(mode="json") for item in entities],
               "evidence": [item.model_dump(mode="json") for item in snapshot.evidence if item.id in refs]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"entities": len(entities), "validation": [item.validation.status for item in entities],
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
