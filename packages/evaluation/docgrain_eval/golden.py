"""The shared wp11/w12 JSONL contract."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    document_id: str
    page: int | None = None
    sheet: str | None = None
    cell: str | None = None
    paragraph_index: int | None = None
    quote: str


class NumberExpected(StrictModel):
    value: int | float | str
    unit: str | None = None


class ConflictExpected(StrictModel):
    value: str | int | float | NumberExpected
    document_id: str


class Question(StrictModel):
    id: str
    workspace_id: str
    document_ids: list[str]
    question: str
    answer_type: Literal["number", "text", "list", "time_range", "unanswerable"]
    expected: NumberExpected | str | list[str] | list[ConflictExpected] | None
    accept: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    category: str
    difficulty: Literal["lookup", "table", "multi_doc", "conflict"]

    @model_validator(mode="after")
    def expected_shape(self):
        value = self.expected
        if self.difficulty == "conflict" and isinstance(value, list) and all(
            isinstance(item, ConflictExpected) for item in value
        ):
            return self
        shapes = {
            "number": isinstance(value, NumberExpected),
            "text": isinstance(value, str),
            "list": isinstance(value, list) and all(isinstance(item, str) for item in value),
            "time_range": isinstance(value, str),
            "unanswerable": value is None,
        }
        if not shapes[self.answer_type]:
            raise ValueError("expected does not match answer_type")
        return self


class TableFact(StrictModel):
    id: str
    document_id: str
    page: int | None = None
    sheet: str | None = None
    table_hint: str
    row_label: str
    column_label: str
    expected: str | int | float


def load_jsonl(path: str | Path, model: type[StrictModel]) -> list:
    records = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                records.append(model.model_validate(json.loads(line)))
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    ids = [record.id for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate ids")
    return records
