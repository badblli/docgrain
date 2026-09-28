"""Small, shared input-format gate for the API and structural worker."""

from __future__ import annotations

from enum import StrEnum
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile


class SourceFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    XLSX = "xlsx"


MIME_TYPES = {
    SourceFormat.PDF: "application/pdf",
    SourceFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    SourceFormat.TXT: "text/plain",
    SourceFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class FormatMismatch(ValueError):
    """Declared format and content disagree, or the format is unsupported."""


class CorruptSource(ValueError):
    """A supported format's bytes cannot be decoded or opened."""


def declared_format(filename: str, mime_type: str) -> SourceFormat:
    try:
        source_format = SourceFormat(Path(filename).suffix.lower().lstrip("."))
    except ValueError as exc:
        raise FormatMismatch("unsupported file extension") from exc
    if mime_type not in (MIME_TYPES[source_format], "application/octet-stream"):
        raise FormatMismatch("MIME type and extension disagree")
    return source_format


def verify_format(data: bytes, source_format: SourceFormat) -> None:
    if source_format is SourceFormat.PDF:
        if not data.startswith(b"%PDF-"):
            raise FormatMismatch("PDF signature does not match extension")
    elif source_format in (SourceFormat.DOCX, SourceFormat.XLSX):
        if not data.startswith(b"PK"):
            raise FormatMismatch("OOXML ZIP signature does not match extension")
        try:
            with ZipFile(BytesIO(data)) as package:
                names = set(package.namelist())
                if "[Content_Types].xml" not in names:
                    raise FormatMismatch("ZIP is not an OOXML package")
                expected = "word/document.xml" if source_format is SourceFormat.DOCX else "xl/workbook.xml"
                other = "xl/workbook.xml" if source_format is SourceFormat.DOCX else "word/document.xml"
                if expected not in names or other in names:
                    raise FormatMismatch("OOXML package type does not match extension")
                if package.testzip() is not None:
                    raise CorruptSource("OOXML package contains a damaged entry")
        except BadZipFile as exc:
            raise CorruptSource("invalid OOXML ZIP package") from exc
    else:
        if b"\x00" in data:
            raise FormatMismatch("binary content is not TXT")
        try:
            data.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise CorruptSource("TXT is not valid UTF-8") from exc
