"""Read-only canonical chunk preview; does not publish, embed or call a model."""

import argparse
from pathlib import Path

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.chunking import ChunkingSpec, derive_chunks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-chars", type=int, default=1600)
    parser.add_argument("--max-table-rows", type=int, default=20)
    parser.add_argument("--header", action="append", default=[], help="canonical-table-id=header-row-count")
    args = parser.parse_args()
    snapshot = CanonicalKnowledgeSnapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
    headers = {}
    for item in args.header:
        identity, count = item.rsplit("=", 1)
        if identity in headers:
            parser.error("duplicate table header declaration")
        headers[identity] = int(count)
    result = derive_chunks(snapshot, ChunkingSpec(max_chars=args.max_chars, max_table_rows=args.max_table_rows,
                                                  table_header_rows=headers))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"{len(result.chunks)} chunks, {len(result.chunk_omissions)} omissions; {args.output}")


if __name__ == "__main__":
    main()
