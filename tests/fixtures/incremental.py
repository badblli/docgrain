"""Explicit synthetic index adapter and new processing revisions for lifecycle tests."""

import hashlib

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot, processing_revision_id
from docgrain_domain.canonical.indexing import EmbeddingSpec, IndexSpec
from docgrain_domain.canonical.lifecycle import ProcessingSpec


def revised(snapshot, mutate, version="m2d-test-2"):
    value = snapshot.model_dump(mode="json")
    mutate(value)
    spec_value = value["knowledge_revision"]["processing"]
    spec_value["mapper_version"] = version
    spec = ProcessingSpec.model_validate(spec_value)
    value["knowledge_revision"]["id"] = processing_revision_id(snapshot.source_version.id, spec)
    value["knowledge_revision"]["parent_revision_id"] = snapshot.knowledge_revision.id
    for producer in value["knowledge_revision"]["producers"]:
        producer["configuration_digest"] = spec.digest
    return CanonicalKnowledgeSnapshot.model_validate(value)


def index_spec(**kwargs):
    return IndexSpec(embedding=EmbeddingSpec(provider="test-only", model="sha256-fixture", version="1", dimensions=2), **kwargs)


class FixtureEmbedder:
    """Never selected by runtime; deterministic controlled test data, not semantic vectors."""

    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def embed(self, text, spec):
        self.calls.append(text)
        if self.fail_at == len(self.calls):
            raise RuntimeError("injected provider failure")
        raw = hashlib.sha256(text.encode()).digest()
        return [raw[i] / 255 for i in range(spec.dimensions)]
