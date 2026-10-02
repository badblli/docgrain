"""Format-aware source locations. Ranges are half-open where applicable."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NormalizedBox(StrictModel):
    """PDF page box with top-left origin and coordinates normalized to [0, 1]."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def within_page(self) -> NormalizedBox:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("bbox exceeds normalized page bounds")
        return self


class PdfPageLocator(StrictModel):
    kind: Literal["pdf_page"] = "pdf_page"
    page_number: int = Field(ge=1)
    bbox: NormalizedBox | None = None


class ImageRegionLocator(StrictModel):
    """Original encoded image pixels, before EXIF orientation; top-left normalized bbox."""

    kind: Literal["image_region"] = "image_region"
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    exif_orientation: int = Field(ge=1, le=8)
    bbox: NormalizedBox


class DocxBlockLocator(StrictModel):
    kind: Literal["docx_block"] = "docx_block"
    part: str = Field(min_length=1, description="DOCX package part, e.g. word/document.xml")
    path: str = Field(min_length=1, description="Stable path within the package part")


class TextSpanLocator(StrictModel):
    """Zero-based Unicode code-point offsets, [start, end), in decoded text."""

    kind: Literal["text_span"] = "text_span"
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> TextSpanLocator:
        if self.end <= self.start:
            raise ValueError("text span end must exceed start")
        return self


_A1_RANGE = re.compile(r"^([A-Za-z]+)([1-9][0-9]*)(?::([A-Za-z]+)([1-9][0-9]*))?$")


def _column_number(value: str) -> int:
    number = 0
    for letter in value:
        number = number * 26 + ord(letter) - ord("A") + 1
    return number


class SpreadsheetRangeLocator(StrictModel):
    kind: Literal["spreadsheet_range"] = "spreadsheet_range"
    sheet: str = Field(min_length=1)
    a1_range: str = Field(min_length=2, description="Uppercase normalized A1 range")

    @field_validator("a1_range")
    @classmethod
    def normalize_a1(cls, value: str) -> str:
        match = _A1_RANGE.fullmatch(value)
        if match is None:
            raise ValueError("invalid A1 range")
        left_col, left_row, right_col, right_row = match.groups()
        if right_col is not None and (
            _column_number(right_col.upper()) < _column_number(left_col.upper())
            or int(right_row) < int(left_row)
        ):
            raise ValueError("A1 range bounds are reversed")
        return value.upper()


class ArtifactObjectLocator(StrictModel):
    kind: Literal["artifact_object"] = "artifact_object"
    artifact_id: str = Field(min_length=1)
    object_path: str | None = None


Locator = Annotated[
    PdfPageLocator | DocxBlockLocator | TextSpanLocator | SpreadsheetRangeLocator | ArtifactObjectLocator | ImageRegionLocator,
    Field(discriminator="kind"),
]
