"""One explicit Gemini visual proposal; consumes API usage, writes no canonical data."""

import argparse
import json
import os
from pathlib import Path

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_worker.selective_vision import (
    GeminiSelectedExtractor,
    Observation,
    prepare_request,
    render_table_page,
    save_proposal,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--task", choices=["room_plan", "table"], required=True)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--page", type=int)
    parser.add_argument("--context", required=True)
    parser.add_argument("--model", default=os.environ.get("GEMINI_MODEL"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-remote", action="store_true", help="Explicitly permit a new provider call")
    args = parser.parse_args()
    snapshot = CanonicalKnowledgeSnapshot.model_validate_json(args.snapshot.read_bytes())
    source = args.source.read_bytes()
    if args.task == "table":
        if args.page is None or args.image is not None:
            parser.error("table requires --page and renders its own source; omit --image")
        image = render_table_page(source, args.page)
        locator = {"kind": "pdf_page_render", "page_number": args.page}
    else:
        if args.image is None or args.page is not None:
            parser.error("room_plan requires --image; omit --page")
        image = args.image.read_bytes()
        node = next((n for n in snapshot.structure if n.id == args.node and n.kind == "asset"), None)
        if node is None:
            parser.error("room_plan requires an existing canonical AssetNode")
        locator = {"kind": "artifact", "artifact_id": node.artifact_id}
    request = prepare_request(snapshot, args.node, image, task=args.task, source_bytes=source,
                              context=args.context, input_locator=locator)
    if args.output.exists():
        cached = json.loads(args.output.read_text(encoding="utf-8"))
        if cached["request"] != request.model_dump(mode="json") or cached["requested_model"] != args.model:
            parser.error("existing proposal belongs to a different request/model; choose another output path")
        Observation.model_validate(cached["observation"])
        print("Existing proposal reused; no provider call.")
    else:
        if not args.allow_remote:
            parser.error("new remote calls are disabled; use --allow-remote only for an authorized run")
        key = os.environ.get("GEMINI_API_KEY")
        if not key or not args.model:
            parser.error("GEMINI_API_KEY and explicit --model/GEMINI_MODEL are required")
        proposal = GeminiSelectedExtractor(key, args.model).extract(request, image)
        save_proposal(args.output, proposal)
        print("Saved proposed observation; canonical/output unchanged.")
