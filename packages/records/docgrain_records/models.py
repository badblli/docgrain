"""Hospitality domain pack: facts are always language-tagged and source-linked."""

from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Language = Annotated[str, Field(pattern=r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")]
PositiveNumber = Annotated[float, Field(gt=0)]
PositiveInt = Annotated[int, Field(gt=0)]
T = TypeVar("T")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Evidence(StrictModel):
    document_id: Text
    locator: Text
    quote: Text


class FieldValue(StrictModel, Generic[T]):
    value: T
    evidence: list[Evidence] = Field(min_length=1)
    lang: Language


class PropertyFields(StrictModel):
    name: FieldValue[Text] | None = None
    address: FieldValue[Text] | None = None
    description: FieldValue[Text] | None = None
    category: FieldValue[Text] | None = None


class RoomTypeFields(StrictModel):
    name: FieldValue[Text] | None = None
    size_m2: FieldValue[PositiveNumber] | None = None
    capacity: FieldValue[PositiveInt] | None = None
    bed_types: FieldValue[list[Text]] | None = None
    view: FieldValue[Text] | None = None
    features: FieldValue[list[Text]] | None = None


class OutletFields(StrictModel):
    name: FieldValue[Text] | None = None
    kind: FieldValue[Literal["restaurant", "bar"]] | None = None
    hours: FieldValue[Text] | None = None
    fee: FieldValue[Text] | None = None
    reservation: FieldValue[Text] | None = None


class ActivityFields(StrictModel):
    name: FieldValue[Text] | None = None
    schedule: FieldValue[Text] | None = None
    age_range: FieldValue[Text] | None = None


class FacilityFields(StrictModel):
    name: FieldValue[Text] | None = None
    kind: FieldValue[Literal["pool", "spa", "beach"]] | None = None
    hours: FieldValue[Text] | None = None
    fee: FieldValue[Text] | None = None


class PolicyFields(StrictModel):
    name: FieldValue[Text] | None = None
    text: FieldValue[Text] | None = None
    applies_to: FieldValue[Text] | None = None


class ContactFields(StrictModel):
    name: FieldValue[Text] | None = None
    kind: FieldValue[Literal["phone", "email", "website", "address", "other"]] | None = None
    value: FieldValue[Text] | None = None


class ServicePriceFields(StrictModel):
    name: FieldValue[Text] | None = None
    amount: FieldValue[Annotated[float, Field(ge=0)]] | None = None
    currency: FieldValue[Text] | None = None
    unit: FieldValue[Text] | None = None
    conditions: FieldValue[Text] | None = None


class RecordBase(StrictModel):
    id: Text
    review_state: Literal["proposed", "needs_review"] = "proposed"
    conflicts: dict[str, list[FieldValue[JsonValue]]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def language_placement(self):
        if self.name is None:
            raise ValueError("a record must have an evidenced name")
        for lang, fields in self.i18n.items():
            for field in type(fields).model_fields:
                value = getattr(fields, field)
                if value is None:
                    continue
                if value.lang != lang:
                    raise ValueError("i18n language key must match the field language")
                if lang.split("-")[0] == "en":
                    raise ValueError("English fields belong in primary values")
        if any(field not in RECORD_MODELS[self.type][1].model_fields or not values
               for field, values in self.conflicts.items()):
            raise ValueError("record conflicts require known fields and candidates")
        if self.conflicts and self.review_state != "needs_review":
            raise ValueError("record conflicts require needs_review")
        return self


class Property(PropertyFields, RecordBase):
    type: Literal["property"] = "property"
    i18n: dict[Language, PropertyFields] = Field(default_factory=dict)


class RoomType(RoomTypeFields, RecordBase):
    type: Literal["room_type"] = "room_type"
    i18n: dict[Language, RoomTypeFields] = Field(default_factory=dict)


class Outlet(OutletFields, RecordBase):
    type: Literal["outlet"] = "outlet"
    i18n: dict[Language, OutletFields] = Field(default_factory=dict)


class Activity(ActivityFields, RecordBase):
    type: Literal["activity"] = "activity"
    i18n: dict[Language, ActivityFields] = Field(default_factory=dict)


class Facility(FacilityFields, RecordBase):
    type: Literal["facility"] = "facility"
    i18n: dict[Language, FacilityFields] = Field(default_factory=dict)


class Policy(PolicyFields, RecordBase):
    type: Literal["policy"] = "policy"
    i18n: dict[Language, PolicyFields] = Field(default_factory=dict)


class Contact(ContactFields, RecordBase):
    type: Literal["contact"] = "contact"
    i18n: dict[Language, ContactFields] = Field(default_factory=dict)


class ServicePrice(ServicePriceFields, RecordBase):
    type: Literal["service_price"] = "service_price"
    i18n: dict[Language, ServicePriceFields] = Field(default_factory=dict)


Record = Annotated[
    Property | RoomType | Outlet | Activity | Facility | Policy | Contact | ServicePrice,
    Field(discriminator="type"),
]
RECORD_MODELS = {
    "property": (Property, PropertyFields),
    "room_type": (RoomType, RoomTypeFields),
    "outlet": (Outlet, OutletFields),
    "activity": (Activity, ActivityFields),
    "facility": (Facility, FacilityFields),
    "policy": (Policy, PolicyFields),
    "contact": (Contact, ContactFields),
    "service_price": (ServicePrice, ServicePriceFields),
}


class RejectedField(StrictModel):
    record_index: int = Field(ge=0)
    record_type: str
    field: str
    lang: str
    reason: Literal["quote_not_found", "document_mismatch", "locator_not_found", "duplicate_language"]
    evidence: list[Evidence]


CollectionFocus = Literal["policy", "service_price", "activity", "facility"]


class ExtractionFailure(StrictModel):
    section: int = Field(ge=1)
    source_keys: list[str] = Field(default_factory=list)
    collection: CollectionFocus | None = None
    reason: Literal["http_error", "connection_error", "invalid_response"]


class CallUsage(StrictModel):
    """One physical request, including retries/fallbacks; no source or credentials."""

    section: int = Field(ge=1)
    collection: CollectionFocus | None = None
    attempt: int = Field(ge=1)
    status_code: int | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ExtractionUsage(StrictModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    missing_usage_calls: int = Field(default=0, ge=0)
    calls: list[CallUsage] = Field(default_factory=list)

    def add(self, call: CallUsage):
        self.calls.append(call)
        self.prompt_tokens += call.prompt_tokens or 0
        self.completion_tokens += call.completion_tokens or 0
        self.total_tokens += call.total_tokens or 0
        if any(value is None for value in (
            call.prompt_tokens, call.completion_tokens, call.total_tokens,
        )):
            self.missing_usage_calls += 1


class ExtractionResult(StrictModel):
    domain: Literal["hospitality"] = "hospitality"
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_id: Text
    lang: Language
    records: list[Record]
    rejected: list[RejectedField] = Field(default_factory=list)
    failures: list[ExtractionFailure] = Field(default_factory=list)


def hospitality_schema() -> dict:
    """JSON Schema for the versioned, verified records.json artifact."""
    return ExtractionResult.model_json_schema()
