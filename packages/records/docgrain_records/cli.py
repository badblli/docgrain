"""Explicit single-document extraction; dry-run reports prompt size only."""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from pydantic import ValidationError

from .api import load_context_bundle
from .extractor import build_messages, extract, extraction_plan
from .match import (
    MatchResult,
    PairClient,
    accept_strong_matches,
    load_records,
    propose_matches,
    summarize_matches,
)
from .match_merge import merge_matches, write_json
from .model import ChatClient
from .models import ExtractionUsage


def run(args):
    if not 1 <= args.concurrency <= 4:
        raise ValueError("concurrency must be between 1 and 4")
    if not 1000 <= args.section_chars <= 10000:
        raise ValueError("section size must be between 1000 and 10000 characters")
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
        plan = extraction_plan(context, args.section_chars, not args.no_focused_passes)
        size = sum(len(message["content"]) for section, collection in plan
                   for message in build_messages(section.context, args.document, lang, collection))
        print(f"İstek boyutu: {size} karakter, yaklaşık {(size + 3) // 4} belirteç; "
              f"{len(plan)} istek (yeniden denemeler hariç)")
        return 0
    chat = ChatClient(args.base_url, args.model, key, args.timeout, args.retries)
    usage = ExtractionUsage()
    try:
        result = extract(context, args.document, lang, chat, section_chars=args.section_chars,
                         concurrency=args.concurrency, focused_passes=not args.no_focused_passes,
                         usage=usage)
    finally:
        chat.close()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "context.md").write_bytes(context.encode("utf-8"))
    source.usage = usage
    (out / "source.json").write_text(
        json.dumps(source.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "records.json").write_text(
        json.dumps(result.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{len(result.records)} kayıt; {len(result.rejected)} alan reddedildi")
    if result.failures:
        print(f"Uyarı: {len(result.failures)} tarama tamamlanamadı; çıkarılan kayıtlar saklandı. "
              "Ayrıntılar records.json içindeki failures alanında.", file=sys.stderr)
        return 1
    return 0


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
    runner.add_argument("--section-chars", type=int, default=8000,
                        help="Her bölüm için hedef karakter sayısı (1000–10000)")
    runner.add_argument("--concurrency", type=int, default=3,
                        help="Aynı anda gönderilen istek sayısı (1–4)")
    runner.add_argument("--no-focused-passes", action="store_true",
                        help="Ek kural, ücret, etkinlik ve tesis taramalarını kapat")
    matcher = commands.add_parser("match")
    matcher.add_argument("--records", required=True)
    matcher.add_argument("--out", required=True)
    matcher.add_argument("--auto-accept", choices=["strong"],
                         help="Güçlü, çelişkisiz eşleşmeleri görünür kurallarla onayla")
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
    merger.add_argument("--auto-accept", choices=["strong"],
                        help="Güçlü eşleşmeleri kaynak kayıtlarıyla yeniden doğrulayıp onayla")
    args = parser.parse_args(argv)
    if args.command == "extract" and not args.dry_run and not args.out:
        parser.error("extract requires --out unless --dry-run")
    try:
        if args.command == "extract":
            return run(args)
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
                if args.auto_accept == "strong":
                    matches = accept_strong_matches(results, matches)
            finally:
                if chat:
                    chat.close()
            write_json(Path(args.out) / "match_proposals.json", matches.model_dump(mode="json"))
            write_json(Path(args.out) / "match_summary.json", summarize_matches(results, matches))
            pruned = sum(c["pruned_pairs"] for c in matches.candidate_counts.values())
            accepted = sum(p.review_state == "accepted" for p in matches.proposals)
            print(f"{len(matches.proposals)} eşleştirme önerisi; {pruned} aday elendi; "
                  f"{accepted} onaylandı; {len(matches.proposals) - accepted} inceleme bekliyor")
        else:
            try:
                matches = MatchResult.model_validate_json(Path(args.matches).read_text(encoding="utf-8"))
            except ValueError as exc:
                raise ValueError("matches file does not match the proposal schema") from exc
            revision = merge_matches(args.records, load_records(args.records), matches,
                                     args.out, args.workspace, args.revision, args.auto_accept)
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
