"""Historical schema compatibility survives the native parser removal."""

import json
from pathlib import Path

from docgrain_domain.canonical.ai_output import output_schema
from docgrain_domain.canonical.schema import generated_core_schema_text


def test_old_schemas_stay_exact_and_new_facts_versioned():
    root = Path("packages/domain/docgrain_domain/canonical/schemas")
    for version in ("0.2.0", "0.3.0", "0.4.0", "0.5.0"):
        assert generated_core_schema_text(version) == (
            root / f"canonical-knowledge-{version}.schema.json"
        ).read_text(encoding="utf-8")
    for version in ("1.0.0", "1.1.0"):
        assert json.dumps(output_schema(version), ensure_ascii=False, sort_keys=True, indent=2) == Path(
            f"tests/fixtures/canonical/ai-document-{version}.schema.json"
        ).read_text(encoding="utf-8")
