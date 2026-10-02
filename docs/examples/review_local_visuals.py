"""Local visual inventory, classification preview and optional selected CPU OCR.

No network, canonical write or model download; input sources must be retained.
"""

import argparse
import json
from pathlib import Path

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.visuals import (
    VisualPreviewRequest,
    preview_visual_review,
    visual_inventory,
)
from docgrain_worker.local_visual_ocr import (
    LocalOCRSession,
    validate_local_ocr_proposal,
)
from docgrain_worker.selective_vision import save_proposal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--decisions", type=Path, help="Pinned VisualPreviewRequest JSON"
    )
    parser.add_argument(
        "--ocr-inputs",
        type=Path,
        help="JSON [{region_id,image_path}] with explicit selections",
    )
    parser.add_argument(
        "--source", type=Path, help="Original source required for selected OCR"
    )
    args = parser.parse_args()
    snapshot = CanonicalKnowledgeSnapshot.model_validate_json(
        args.snapshot.read_bytes()
    )
    inventory = visual_inventory(snapshot)
    args.output.mkdir(parents=True, exist_ok=True)
    save_proposal(
        args.output / (inventory.id + ".json"), inventory.model_dump(mode="json")
    )
    if args.decisions:
        request = VisualPreviewRequest.model_validate_json(args.decisions.read_bytes())
        preview = preview_visual_review(snapshot, request)
        save_proposal(
            args.output / (preview.id + ".json"), preview.model_dump(mode="json")
        )
    if args.ocr_inputs:
        if args.source is None:
            parser.error("selected OCR requires --source")
        source = args.source.read_bytes()
        selections = json.loads(args.ocr_inputs.read_text(encoding="utf-8"))
        if not isinstance(selections, list) or not 1 <= len(selections) <= 100:
            parser.error("select 1..100 local OCR regions")
        session = LocalOCRSession()
        for selection in selections:
            image = Path(selection["image_path"]).read_bytes()
            path = args.output / (selection["region_id"] + "-ocr.json")
            if path.exists():
                cached = json.loads(path.read_text(encoding="utf-8"))
                validate_local_ocr_proposal(snapshot, inventory, cached, source, image)
                if cached["execution_status"] != "done":
                    raise ValueError(
                        "existing failed proposal retained; choose a new output directory to retry"
                    )
                print(f"Reused {selection['region_id']}; no OCR inference.")
                continue
            proposal = session.extract(
                snapshot, inventory, selection["region_id"], source, image
            )
            save_proposal(path, proposal)
            print(
                f"Saved {selection['region_id']}: {proposal['execution_status']}; proposed, not applied."
            )
    print(f"Inventory: {len(inventory.regions)} regions; canonical/output unchanged.")


if __name__ == "__main__":
    main()
