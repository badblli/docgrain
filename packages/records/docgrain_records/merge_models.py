"""Workspace merge contracts built on the verified wp41 record models."""

from typing import Literal

from pydantic import Field, JsonValue, computed_field, model_validator

from .models import Evidence, Language, Record, StrictModel, Text

ReviewState = Literal["proposed", "needs_review", "accepted", "rejected"]


class SourceRecord(StrictModel):
    # Caller-owned identity, stable across edits; wp41's positional id is not one.
    source_identity: Text
    aliases: list[Text] = Field(default_factory=list)
    # Explicit matcher vetoes apply to weak normalized-name matching only.
    match_exclusions: list[Text] = Field(default_factory=list)
    record: Record


class MergeDocument(StrictModel):
    workspace_id: Text
    document_id: Text
    source_version_id: Text
    knowledge_revision_id: Text
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    context: Text
    document_name: Text | None = None
    records: list[SourceRecord]

    @model_validator(mode="after")
    def unique_identities(self):
        keys = [(item.record.type, item.source_identity) for item in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate source identity in document")
        return self


class SourcePin(StrictModel):
    document_id: Text
    source_version_id: Text
    knowledge_revision_id: Text
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    document_name: Text | None = None


class VersionedEvidence(Evidence):
    source_version_id: Text
    knowledge_revision_id: Text


class UserEditEvidence(StrictModel):
    kind: Literal["user_edit"] = "user_edit"
    at: Text
    note: str


class FactCandidate(StrictModel):
    id: Text
    value: JsonValue
    lang: Language
    evidence: list[VersionedEvidence | UserEditEvidence] = Field(min_length=1)
    review_state: ReviewState = "proposed"


class MergedField(StrictModel):
    primary_lang: Language
    candidates: list[FactCandidate] = Field(min_length=1)
    # Record-local, language-specific override after an explicit "all" answer.
    multi_value_languages: list[Language] = Field(default_factory=list)

    @computed_field
    @property
    def review_state(self) -> ReviewState:
        states = {candidate.review_state for candidate in self.candidates}
        if "needs_review" in states:
            return "needs_review"
        if "proposed" in states:
            return "proposed"
        return "accepted" if "accepted" in states else "rejected"

    @computed_field
    @property
    def primary(self) -> FactCandidate | None:
        """A display proposal is never an export approval; conflicts have no winner."""
        choices = [c for c in self.candidates if c.lang == self.primary_lang
                   and c.review_state != "rejected"]
        accepted = [c for c in choices if c.review_state == "accepted"]
        if choices and self.primary_lang in self.multi_value_languages:
            from .multivalue import combine

            return combine(accepted or choices)
        if accepted:
            return accepted[0]
        return choices[0] if len(choices) == 1 else None

    @computed_field
    @property
    def i18n(self) -> dict[str, list[FactCandidate]]:
        return {lang: [c for c in self.candidates if c.lang == lang]
                for lang in sorted({c.lang for c in self.candidates})
                if lang.split("-")[0] != "en"}

    @computed_field
    @property
    def conflicts(self) -> dict[str, list[FactCandidate]]:
        return {lang: [c for c in self.candidates if c.lang == lang]
                for lang in sorted({c.lang for c in self.candidates})
                if sum(c.lang == lang for c in self.candidates) > 1}

    def accepted(self, lang: str | None = None) -> FactCandidate | None:
        """Exporter gate: only an explicit acceptance returns a value."""
        language = lang or self.primary_lang
        candidates = [c for c in self.candidates if c.lang == language
                      and c.review_state == "accepted"]
        if candidates and language in self.multi_value_languages:
            from .multivalue import combine

            return combine(candidates)
        return candidates[0] if candidates else None


class MergedRecord(StrictModel):
    id: Text
    type: Text
    fields: dict[str, MergedField]


class ReviewDecision(StrictModel):
    record_id: Text
    field: Text
    candidate_id: Text
    action: Literal["accepted", "rejected"]
    reviewer: Text
    reason: Text


class MatchIssue(StrictModel):
    key: Text
    source_keys: list[str]
    reason: Literal["ambiguous_normalized_key", "excluded_pair"] = "ambiguous_normalized_key"


class AliasDecision(StrictModel):
    """Explicit consolidation of previously distinct IDs; field review is separate."""

    keep_id: Text
    retired_id: Text
    proposal_ids: list[Text] = Field(min_length=1)
    reviewer: Text
    reason: Text


class AnswerHistory(StrictModel):
    question_id: Text
    record_id: Text
    field: Text
    lang: Language
    candidate_id: Text
    candidate_ids: list[Text] = Field(default_factory=list)
    all: bool = False
    actor: Literal["local"] = "local"
    at: Text
    note: str


class MergeRevision(StrictModel):
    workspace_id: Text
    id: Text
    documents: list[SourcePin]
    records: list[MergedRecord]
    match_issues: list[MatchIssue] = Field(default_factory=list)
    decisions: list[ReviewDecision] = Field(default_factory=list)
    alias_decisions: list[AliasDecision] = Field(default_factory=list)
    # Exact accepted schema snapshot makes old publications independent of later discovery.
    workspace_schema: dict | None = None
    parent_id: Text | None = None
    lineage_id: Text | None = None
    updated_at: Text | None = None
    history: list[AnswerHistory] = Field(default_factory=list)


class FieldChange(StrictModel):
    record_id: Text
    field: Text
    kind: Literal["added", "removed", "changed"]
    value_changed: bool
    i18n_changed: bool
    evidence_changed: bool
    conflicts_changed: bool
    review_changed: bool
    before: MergedField | None
    after: MergedField | None

    @computed_field
    @property
    def evidence_only(self) -> bool:
        return self.evidence_changed and not any((self.value_changed, self.i18n_changed,
                                                 self.conflicts_changed, self.review_changed))


class RevisionDiff(StrictModel):
    workspace_id: Text
    before_id: Text
    after_id: Text
    added_records: list[str]
    removed_records: list[str]
    fields: list[FieldChange]


class MergeState(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    workspace_id: Text
    # Multimaps keep ambiguous historical keys visible, including deleted records.
    identity_map: dict[str, list[str]] = Field(default_factory=dict)
    revisions: dict[str, MergeRevision] = Field(default_factory=dict)
    request_digests: dict[str, str] = Field(default_factory=dict)
