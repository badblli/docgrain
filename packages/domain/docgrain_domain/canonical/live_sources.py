"""Source observations and deterministic change hints, independent of watcher runtimes."""

from typing import Literal

from pydantic import Field, model_validator

from .identity import canonical_json_bytes
from .lifecycle import logical_document_id
from .locations import StrictModel


class SourceObservation(StrictModel):
    source_key: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)


class SourceChange(StrictModel):
    id: str
    workspace_id: str
    connector_id: str
    generation: int = Field(ge=1)
    source_key: str
    document_id: str
    action: Literal["upsert", "delete"]
    observation: SourceObservation | None

    @model_validator(mode="after")
    def consistent(self):
        if (self.action == "delete") != (self.observation is None):
            raise ValueError("delete requires tombstone; upsert requires observation")
        if self.observation and self.observation.source_key != self.source_key:
            raise ValueError("source key mismatch")
        if self.document_id != logical_document_id(self.workspace_id, self.connector_id, self.source_key):
            raise ValueError("document scope mismatch")
        return self


def changes(workspace: str, connector: str, generation: int,
            previous: dict[str, SourceObservation], current: dict[str, SourceObservation]) -> list[SourceChange]:
    import hashlib

    result = []
    for key in sorted(previous.keys() | current.keys()):
        if previous.get(key) == current.get(key):
            continue
        payload = {
            "workspace_id": workspace,
            "connector_id": connector,
            "generation": generation,
            "source_key": key,
            "document_id": logical_document_id(workspace, connector, key),
            "action": "upsert" if key in current else "delete",
            "observation": current[key].model_dump(mode="json") if key in current else None,
        }
        identity = "source_change_" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        result.append(SourceChange(id=identity, **payload))
    return result
