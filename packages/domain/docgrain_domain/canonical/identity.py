"""Explicit, document-scoped identity policy and deterministic JSON encoding."""

from __future__ import annotations

import hashlib
import json
import uuid

from pydantic import JsonValue

IDENTITY_POLICY_VERSION = "0.1.0"


def new_canonical_id(prefix: str) -> str:
    """Random 128-bit IDs for source and revision identities."""
    return f"{prefix}_{uuid.uuid4().hex}"


def canonical_json_bytes(value: JsonValue) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def deterministic_item_id(document_id: str, kind: str, identity_key: str, *,
                          policy_version: str = IDENTITY_POLICY_VERSION) -> str:
    """Use an explicit stable key; parser position, mutable text and revision are not inputs.

    This does not perform automatic matching across sources or documents.
    """
    if not document_id or not kind or not identity_key:
        raise ValueError("document_id, kind and explicit identity_key are required")
    if policy_version not in {"0.1.0", "0.2.0"}:
        raise ValueError("unsupported identity policy")
    payload = canonical_json_bytes([policy_version, document_id, kind, identity_key])
    return f"{kind}_{hashlib.sha256(payload).hexdigest()[:32]}"
