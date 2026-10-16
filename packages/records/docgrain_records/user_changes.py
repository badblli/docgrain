"""Immutable user additions to an accepted workspace schema and record revision."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import Field, JsonValue

from .discovery_models import (
    Collection,
    CollectionField,
    CollectionKey,
    FieldType,
    Key,
    Label,
    WorkspaceSchema,
)
from .merge_models import (
    FactCandidate,
    MergedField,
    MergedRecord,
    MergeRevision,
    UserChange,
    UserEditEvidence,
)
from .models import StrictModel, Text
from .runtime import RuntimeRecords, revision_runtime


class NewField(StrictModel):
    key: Key
    label: Text
    type: FieldType
    description: str | None = None


class NewCollection(StrictModel):
    key: CollectionKey
    label: Text
    identity: Key
    fields: list[NewField] = Field(min_length=1)


class ManualValue(StrictModel):
    value: JsonValue
    note: str = ""
    who: Text = "local"


class ManualRecord(StrictModel):
    values: dict[str, JsonValue] = Field(min_length=1)
    note: str = ""
    who: Text = "local"


def _next(base, kind, collection, who, *, field=None, record_id=None, note=""):
    revision = base.model_copy(deep=True)
    revision.id = "rev_" + uuid4().hex
    revision.parent_id = base.id
    revision.lineage_id = base.lineage_id or base.id
    revision.updated_at = datetime.now(UTC).isoformat()
    revision.user_changes.append(UserChange(kind=kind, collection=collection, field=field,
                                            record_id=record_id, who=who,
                                            at=revision.updated_at, note=note))
    return revision


def _definition(field):
    return CollectionField(key=field.key, type=field.type, unit=None,
                           label_i18n=[Label(lang="en", value=field.label),
                                       Label(lang="tr", value=field.label)],
                           description=field.description, review_state="accepted")


def add_field(base: MergeRevision, collection: str, field: NewField, who="local"):
    if base.workspace_schema is None:
        raise ValueError("accepted workspace schema required")
    revision = _next(base, "add_field", collection, who, field=field.key)
    schema = WorkspaceSchema.model_validate(revision.workspace_schema)
    target = next((item for item in schema.collections if item.key == collection), None)
    if target is None:
        raise ValueError("collection unknown")
    if field.key in {item.key for item in target.fields}:
        raise ValueError("field already exists")
    target.fields.append(_definition(field))
    schema.version += 1
    revision.workspace_schema = schema.model_dump(mode="json")
    RuntimeRecords(schema)
    return MergeRevision.model_validate_json(revision.model_dump_json(round_trip=True))


def add_collection(base: MergeRevision, value: NewCollection, who="local"):
    if base.workspace_schema is None:
        raise ValueError("accepted workspace schema required")
    revision = _next(base, "add_collection", value.key, who)
    schema = WorkspaceSchema.model_validate(revision.workspace_schema)
    if value.key in {item.key for item in schema.collections}:
        raise ValueError("collection already exists")
    if len({field.key for field in value.fields}) != len(value.fields):
        raise ValueError("duplicate field")
    if value.identity not in {field.key for field in value.fields}:
        raise ValueError("identity must be one of the fields")
    schema.collections.append(Collection(key=value.key,
        label_i18n=[Label(lang="en", value=value.label), Label(lang="tr", value=value.label)],
        description=value.label, fields=[_definition(field) for field in value.fields],
        examples=[], identity=value.identity, review_state="accepted"))
    schema.version += 1
    revision.workspace_schema = schema.model_dump(mode="json")
    RuntimeRecords(schema)
    return MergeRevision.model_validate_json(revision.model_dump_json(round_trip=True))


def _candidate(value, note, who, at, lang="tr"):
    return FactCandidate(id="fact_" + uuid4().hex, value=value, lang=lang,
                         evidence=[UserEditEvidence(who=who, at=at, note=note)],
                         review_state="accepted")


def set_value(base: MergeRevision, record_id: str, field: str, update: ManualValue):
    original = next((record for record in base.records if record.id == record_id), None)
    if original is None:
        raise ValueError("record unknown")
    value = revision_runtime(base).validate_value(original.type, field, update.value)
    revision = _next(base, "set_value", original.type, update.who, record_id=record_id,
                     field=field, note=update.note)
    record = next(record for record in revision.records if record.id == record_id)
    merged = record.fields.get(field)
    if merged is None:
        record.fields[field] = MergedField(primary_lang="tr", candidates=[
            _candidate(value, update.note, update.who, revision.updated_at)])
    else:
        # The shown value is the primary language; other languages keep their own values
        # (same per-language rule as an EditAnswer in review.answer_revision).
        lang = merged.primary_lang
        for candidate in merged.candidates:
            if candidate.lang == lang and candidate.review_state == "accepted":
                candidate.review_state = "rejected"
        merged.candidates.append(_candidate(value, update.note, update.who, revision.updated_at, lang))
    return MergeRevision.model_validate_json(revision.model_dump_json(round_trip=True))


def add_record(base: MergeRevision, collection: str, entry: ManualRecord):
    runtime = revision_runtime(base)
    if collection not in runtime.models:
        raise ValueError("collection unknown")
    identity = runtime.identities[collection]
    if identity not in entry.values:
        raise ValueError("record identity is required")
    values = {key: runtime.validate_value(collection, key, value)
              for key, value in entry.values.items()}
    record_id = "rec_" + uuid4().hex
    revision = _next(base, "add_record", collection, entry.who,
                     record_id=record_id, note=entry.note)
    revision.records.append(MergedRecord(id=record_id, type=collection, fields={
        key: MergedField(primary_lang="tr", candidates=[
            _candidate(value, entry.note, entry.who, revision.updated_at)])
        for key, value in values.items()}))
    return MergeRevision.model_validate_json(revision.model_dump_json(round_trip=True))
