"""Explicit single-document extraction; dry-run reports prompt size only."""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from pydantic import ValidationError

from .api import load_context_bundle
from .extractor import build_messages, extract
from .match import (
    MatchResult,
    PairClient,
    load_records,
    propose_matches,
    summarize_matches,
)
from .match_merge import merge_matches, write_json
from .model import ChatClient


def run(args):
    key = None
    if not args.dry_run:
        if not args.base_url or not args.model or not args.api_key_env:
            raise ValueError("model run requires --base-url, --model and --api-key-env")
        key = os.environ.get(args.api_key_env)
        if not key:
            raise ValueError("specified API key environment variable is empty")
    with httpx.Client(base_url=args.api.rstrip("/"), timeout=30) as api:
        context, lang, source = load_context_bundle(api, args.document, args.lang,
                                                     require_pins=not args.dry_run)
    if args.dry_run:
        messages = build_messages(context, args.document, lang)
        size = sum(len(message["content"]) for message in messages)
        print(f"İstek boyutu: {size} karakter, yaklaşık {(size + 3) // 4} belirteç")
        return
    chat = ChatClient(args.base_url, args.model, key, args.timeout, args.retries)
    try:
        result = extract(context, args.document, lang, chat)
    finally:
        chat.close()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "context.md").write_bytes(context.encode("utf-8"))
    (out / "source.json").write_text(
        json.dumps(source.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "records.json").write_text(
        json.dumps(result.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{len(result.records)} kayıt; {len(result.rejected)} alan reddedildi")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="docgrain-records")
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("extract")
    runner.add_argument("--document", required=True)
    runner.add_argument("--api", required=True)
    runner.add_argument("--lang", help="Kaynak dili (en, tr, de, ru); bilinmiyorsa belgede belirlenir")
    runner.add_argument("--base-url")
    runner.add_argument("--model")
    runner.add_argument("--api-key-env")
    runner.add_argument("--out")
    runner.add_argument("--dry-run", action="store_true")
    runner.add_argument("--timeout", type=float, default=60)
    runner.add_argument("--retries", type=int, default=3)
    matcher = commands.add_parser("match")
    matcher.add_argument("--records", required=True)
    matcher.add_argument("--out", required=True)
    matcher.add_argument("--base-url")
    matcher.add_argument("--model")
    matcher.add_argument("--api-key-env")
    matcher.add_argument("--timeout", type=float, default=60)
    matcher.add_argument("--retries", type=int, default=3)
    merger = commands.add_parser("merge")
    merger.add_argument("--records", required=True)
    merger.add_argument("--matches", required=True)
    merger.add_argument("--out", required=True)
    merger.add_argument("--workspace", help="Kaynak dosyalarındaki çalışma alanını doğrula")
    merger.add_argument("--revision")
    args = parser.parse_args(argv)
    if args.command == "extract" and not args.dry_run and not args.out:
        parser.error("extract requires --out unless --dry-run")
    try:
        if args.command == "extract":
            run(args)
        elif args.command == "match":
            configured = [args.base_url, args.model, args.api_key_env]
            chat = None
            if any(configured):
                if not all(configured):
                    raise ValueError("model run requires --base-url, --model and --api-key-env")
                key = os.environ.get(args.api_key_env)
                if not key:
                    raise ValueError("specified API key environment variable is empty")
                chat = PairClient(args.base_url, args.model, key, args.timeout, args.retries)
            try:
                results = load_records(args.records)
                matches = propose_matches(results, chat)
            finally:
                if chat:
                    chat.close()
            write_json(Path(args.out) / "match_proposals.json", matches.model_dump(mode="json"))
            write_json(Path(args.out) / "match_summary.json", summarize_matches(results, matches))
            print(f"{len(matches.proposals)} eşleştirme önerisi; onay bekliyor")
        else:
            try:
                matches = MatchResult.model_validate_json(Path(args.matches).read_text(encoding="utf-8"))
            except ValueError as exc:
                raise ValueError("matches file does not match the proposal schema") from exc
            revision = merge_matches(args.records, load_records(args.records), matches,
                                     args.out, args.workspace, args.revision)
            print(f"{len(revision.records)} kayıt; alan değerleri inceleme bekliyor")
    except httpx.HTTPStatusError as exc:
        print(f"Hata: HTTP {exc.response.status_code}", file=sys.stderr)
        return 1
    except httpx.HTTPError:
        print("Hata: Bağlantı kurulamadı", file=sys.stderr)
        return 1
    except ValidationError:
        print("Hata: Girdi dosyası beklenen yapıda değil", file=sys.stderr)
        return 1
    except (ValueError, OSError) as exc:
        # Validation errors are sanitized at the boundaries; never print model/source bodies.
        print(f"Hata: {exc}" if isinstance(exc, ValueError) else "Hata: Dosya yazılamadı", file=sys.stderr)
        return 1
    return 0
