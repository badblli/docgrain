"""Reviewable proposals and immutable, explicitly accepted workspace schema versions."""

import json
import re
from hashlib import sha256
from pathlib import Path

from .discovery import source_pins, verify_examples
from .discovery_models import DiscoveryDocument, WorkspaceSchema
from .extractor import _blocks


def source_directory(root, source):
    identity = f"{source.document_id}\n{source.knowledge_revision_id}\n{source.context_sha256}"
    return Path(root) / "schema.sources" / sha256(identity.encode()).hexdigest()


def write_proposal(root, schema, documents):
    root = Path(root)
    if schema.review_state != "proposed" or schema.version is not None:
        raise ValueError("only an unversioned proposal can be written")
    if schema.sources != source_pins(documents, schema.workspace_id):
        raise ValueError("proposal pins do not match its source documents")
    latest_schema(root, schema.workspace_id)
    proposal_path = root / "schema.proposed.json"
    if proposal_path.exists():
        previous = WorkspaceSchema.model_validate_json(proposal_path.read_text(encoding="utf-8"))
        if previous.workspace_id != schema.workspace_id:
            raise ValueError("output proposal belongs to another workspace")
    by_id = {doc.source.document_id: doc for doc in documents}
    for source in schema.sources:
        path = source_directory(root, source)
        path.mkdir(parents=True, exist_ok=True)
        context = by_id[source.document_id].context.encode("utf-8")
        target = path / "context.md"
        if target.exists() and target.read_bytes() != context:
            raise ValueError("stored discovery source was changed")
        target.write_bytes(context)
    root.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(
        schema.model_dump_json(indent=2) + "\n", encoding="utf-8",
    )


def latest_schema(root, workspace_id):
    versions = []
    for path in Path(root).glob("schema.v*.json"):
        match = re.fullmatch(r"schema\.v([1-9]\d*)\.json", path.name)
        if match:
            versions.append((int(match.group(1)), path))
    latest = None
    for version, path in sorted(versions):
        schema = WorkspaceSchema.model_validate_json(path.read_text(encoding="utf-8"))
        if (schema.workspace_id != workspace_id or schema.review_state != "accepted"
                or schema.version != version):
            raise ValueError("stored schema has an invalid workspace, version or review state")
        latest = schema
    return latest


def accept_schema(proposal_path, out):
    """Edited review states are explicit decisions; no automatic/model acceptance."""
    path = Path(proposal_path)
    proposal = WorkspaceSchema.model_validate_json(path.read_text(encoding="utf-8"))
    if proposal.review_state != "proposed" or proposal.version is not None:
        raise ValueError("accept requires an unversioned proposed schema")
    blocks = {}
    for source in proposal.sources:
        context = (source_directory(path.parent, source) / "context.md").read_bytes()
        if sha256(context).hexdigest() != source.context_sha256:
            raise ValueError("schema source context no longer matches its pin")
        blocks[source.document_id] = _blocks(context.decode("utf-8"))
    accepted = []
    for collection in proposal.collections:
        if collection.review_state == "rejected":
            continue
        if collection.review_state != "accepted":
            raise ValueError("every retained collection must be explicitly accepted")
        collection.fields = [field for field in collection.fields
                             if field.review_state != "rejected"]
        if not collection.fields or any(field.review_state != "accepted" or field.alternatives
                                        for field in collection.fields):
            raise ValueError("every retained field must be accepted with conflicts resolved")
        keys = {field.key for field in collection.fields}
        for example in collection.examples:
            example.values = [value for value in example.values if value.key in keys]
        collection.examples = [example for example in collection.examples if example.values]
        rejected = []
        verify_examples(collection, blocks, rejected)
        supported = {value.key for example in collection.examples for value in example.values}
        if rejected or not collection.examples or supported != keys:
            raise ValueError("accepted fields require typed examples with verified source quotes")
        accepted.append(collection)
    if not accepted:
        raise ValueError("schema acceptance requires at least one supported collection")
    previous = latest_schema(out, proposal.workspace_id)
    proposal.collections = accepted
    proposal.review_state = "accepted"
    proposal.version = previous.version + 1 if previous else 1
    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    # Keep accepted sources with the version, including when --out differs from the proposal dir.
    for source in proposal.sources:
        destination = source_directory(root, source)
        destination.mkdir(parents=True, exist_ok=True)
        content = (source_directory(path.parent, source) / "context.md").read_bytes()
        target = destination / "context.md"
        if target.exists() and target.read_bytes() != content:
            raise ValueError("stored discovery source was changed")
        target.write_bytes(content)
    target = root / f"schema.v{proposal.version}.json"
    with target.open("x", encoding="utf-8") as file:
        file.write(proposal.model_dump_json(indent=2) + "\n")
    return proposal


def load_source_documents(directory, workspace_id):
    """Read pinned normalized contexts; records.json and hospitality types are irrelevant."""
    documents = []
    for path in sorted(Path(directory).rglob("source.json")):
        document = DiscoveryDocument.model_validate({
            "source": json.loads(path.read_text(encoding="utf-8")),
            "context": (path.parent / "context.md").read_text(encoding="utf-8"),
        })
        documents.append(document)
    source_pins(documents, workspace_id)
    return documents
