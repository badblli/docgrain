"""Prefixed identifiers.

Every identifier carries its type as a prefix so that a stray id in a log,
a URL or a chunk payload is self-describing. Prefixes are part of the public
contract and must not change.
"""

from __future__ import annotations

import secrets

PREFIXES: dict[str, str] = {
    "workspace": "ws",
    "document": "doc",
    "version": "dver",
    "page": "pg",
    "section": "sec",
    "asset": "ast",
    "table": "tbl",
    "chunk": "chk",
    "embedding": "emb",
    "index_record": "idx",
    "job": "job",
}


def new_id(kind: str) -> str:
    """Return a fresh identifier for ``kind`` (e.g. ``chk_9f21ab04``)."""
    try:
        prefix = PREFIXES[kind]
    except KeyError as exc:  # pragma: no cover - programming error
        raise ValueError(f"unknown id kind: {kind!r}") from exc
    return f"{prefix}_{secrets.token_hex(4)}"


def kind_of(identifier: str) -> str | None:
    """Return the kind an identifier belongs to, or None if unrecognised."""
    prefix = identifier.split("_", 1)[0]
    for kind, known in PREFIXES.items():
        if known == prefix:
            return kind
    return None
