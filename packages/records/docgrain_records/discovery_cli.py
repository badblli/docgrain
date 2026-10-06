"""Explicit workspace discovery; default only scans local/API normalized data."""

import json
import os
from pathlib import Path

import httpx

from .api import load_context_bundle
from .discovery import DiscoveryClient, build_discovery_messages, discover, source_pins
from .discovery_models import DiscoveryDocument
from .discovery_signals import detect_signals
from .discovery_store import (
    accept_schema,
    latest_schema,
    load_source_documents,
    write_proposal,
)


def add_discovery_commands(commands):
    runner = commands.add_parser("discover")
    runner.add_argument("--workspace", required=True)
    inputs = runner.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--api", help="Belge hizmetinin adresi")
    inputs.add_argument("--sources", help="source.json ve context.md içeren klasör")
    runner.add_argument("--out", required=True)
    runner.add_argument("--base-url")
    runner.add_argument("--model")
    runner.add_argument("--api-key-env")
    runner.add_argument("--dry-run", action="store_true")
    runner.add_argument("--timeout", type=float, default=60)
    runner.add_argument("--retries", type=int, default=3)
    runner.add_argument("--max-prompt-chars", type=int, default=120000,
                        help="İstek boyutu sınırı; aşılırsa gönderim yapılmaz")
    accepter = commands.add_parser("accept-schema")
    accepter.add_argument("--proposal", required=True)
    accepter.add_argument("--out", required=True)


def load_workspace_documents(api_url, workspace_id):
    documents = []
    with httpx.Client(base_url=api_url.rstrip("/"), timeout=30) as api:
        offset = 0
        ids = []
        while True:
            response = api.get("/v1/documents", params={"limit": 50, "offset": offset})
            response.raise_for_status()
            page = response.json()
            if not isinstance(page, list):
                raise ValueError("document list is invalid")  # noqa: TRY004 - CLI boundary
            for entry in page:
                if not isinstance(entry, dict) or not isinstance(entry.get("document"), dict):
                    raise ValueError("document list is invalid")  # noqa: TRY004 - CLI boundary
                document = entry["document"]
                if document.get("workspace_id") == workspace_id:
                    if not isinstance(document.get("id"), str):
                        raise ValueError("document list is invalid")
                    ids.append(document["id"])
            if len(page) < 50:
                break
            offset += len(page)
        for document_id in sorted(ids):
            context, _, source = load_context_bundle(api, document_id)
            documents.append(DiscoveryDocument(source=source, context=context))
    source_pins(documents, workspace_id)
    return documents


def run_discovery(args):
    if args.command == "accept-schema":
        schema = accept_schema(args.proposal, args.out)
        print(f"{len(schema.collections)} bilgi listesi onaylandı; sürüm {schema.version}")
        return 0
    configured = [args.base_url, args.model, args.api_key_env]
    key = None
    if any(configured) and not all(configured):
        raise ValueError("model run requires --base-url, --model and --api-key-env")
    if all(configured) and not args.dry_run:
        key = os.environ.get(args.api_key_env)
        if not key:
            raise ValueError("specified API key environment variable is empty")
    if args.max_prompt_chars < 1:
        raise ValueError("prompt size limit must be positive")
    documents = (load_source_documents(args.sources, args.workspace) if args.sources else
                 load_workspace_documents(args.api, args.workspace))
    existing = latest_schema(args.out, args.workspace)
    messages = build_discovery_messages(documents, args.workspace, existing)
    size = sum(len(message["content"]) for message in messages)
    if args.dry_run:
        print(f"İstek boyutu: {size} karakter, yaklaşık {(size + 3) // 4} belirteç; "
              f"{len(detect_signals(documents))} tekrar eden yapı")
        return 0
    if key and size > args.max_prompt_chars:
        raise ValueError("discovery prompt exceeds --max-prompt-chars; no model request sent")
    chat = DiscoveryClient(args.base_url, args.model, key, args.timeout, args.retries) if key else None
    try:
        schema = discover(documents, args.workspace, chat, existing)
    finally:
        if chat:
            chat.close()
    write_proposal(args.out, schema, documents)
    (Path(args.out) / "discovery.signals.json").write_text(
        json.dumps(detect_signals(documents), ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"{len(schema.collections)} bilgi listesi önerildi; {len(schema.rejected)} örnek alan elendi")
    if not chat:
        print("Yapılar tarandı. Öneri üretmek için model bağlantısını açıkça belirtin.")
    return 0
