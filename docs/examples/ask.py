"""Explicit opt-in reference loop. Setup and examples: docs/examples/ai-access.md."""

import argparse
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/access"))

from docgrain_access.ask import OpenAICompatibleClient, ask
from docgrain_access.client import AccessClient, AccessError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--api-url", default=os.environ.get("DOCGRAIN_API_URL"))
    parser.add_argument("--workspace", default=os.environ.get("DOCGRAIN_WORKSPACE"))
    parser.add_argument("--revision", default=os.environ.get("DOCGRAIN_REVISION"))
    parser.add_argument("--enable-model", action="store_true", help="Explicitly enable model calls")
    parser.add_argument("--preview", action="store_true", help="Explicitly request unapproved data")
    args = parser.parse_args(argv)
    if not args.enable_model:
        print("Model kapalı. Çalıştırmak için --enable-model seçeneğini kullanın.")
        return 0
    config = [os.environ.get(key) for key in ("AI_BASE_URL", "AI_MODEL", "AI_API_KEY")]
    if not args.api_url or not args.workspace or not all(config):
        parser.error("Configure DOCGRAIN_API_URL, DOCGRAIN_WORKSPACE, AI_BASE_URL, AI_MODEL, AI_API_KEY")
    access = AccessClient(args.api_url, args.workspace, args.revision)
    model = OpenAICompatibleClient(*config)
    try:
        print(ask(args.question, access, model, preview=args.preview))
    except AccessError:
        print("Docgrain API'sine ulaşılamadı ya da istek reddedildi.", file=sys.stderr)
        return 1
    except httpx.TimeoutException:
        print("Model zamanında yanıt vermedi; tekrar deneyin.", file=sys.stderr)
        return 1
    except httpx.HTTPStatusError as error:
        # Only the status code: raw exceptions can contain credentials or URLs.
        print(f"Model hizmeti hata döndürdü (HTTP {error.response.status_code}).", file=sys.stderr)
        return 1
    except (httpx.HTTPError, KeyError, ValueError):
        print("Model yanıtı okunamadı.", file=sys.stderr)
        return 1
    finally:
        model.close()
        access.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
