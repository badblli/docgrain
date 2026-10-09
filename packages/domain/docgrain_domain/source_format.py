"""Small, shared input-format gate for the API and structural worker."""

from __future__ import annotations

import csv
import json
import re
import tarfile
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .docling_formats import (
    BROWSER_MIME_ALIASES,
    EXTENSION_MIME,
    NEVER_AVAILABLE,
    NOT_ENABLED_MESSAGE,
    ORIGINAL_FORMATS,
    SPECS,
    extension_index,
)

# KULLANILMIYOR (karar 18): WP106 öncesi elle yazılmış altı biçimlik liste. Değerler aynen korunuyor;
# SourceFormat artık Docling'in InputFormat tablosundan türetiliyor (docling_formats.py).
# class SourceFormat(StrEnum):
#     PDF = "pdf"
#     DOCX = "docx"
#     TXT = "txt"
#     XLSX = "xlsx"
#     PNG = "png"
#     JPEG = "jpeg"

# Derived from Docling's InputFormat (docling_formats.SPECS); the first six keep their stored values.
SourceFormat = StrEnum(
    "SourceFormat",
    [(value.upper(), value) for value in ORIGINAL_FORMATS]
    + [(value.upper(), value) for value in SPECS if value not in ORIGINAL_FORMATS],
    module=__name__,
    qualname="SourceFormat",
)


MIME_TYPES = {
    SourceFormat.PDF: "application/pdf",
    SourceFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    SourceFormat.TXT: "text/plain",
    SourceFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    SourceFormat.PNG: "image/png",
    SourceFormat.JPEG: "image/jpeg",
}

IMAGE_FORMATS = frozenset(SourceFormat(v) for v, spec in SPECS.items() if spec.docling_format == "image")
XML_FORMATS = frozenset(SourceFormat(v) for v in ("xml_uspto", "xml_jats", "xml_xbrl", "xml_doclang"))
_ORIGINAL_EXTENSIONS = {"pdf", "docx", "txt", "xlsx", "png", "jpeg", "jpg"}


class FormatMismatch(ValueError):
    """Declared format and content disagree, or the format is unsupported."""


class CorruptSource(ValueError):
    """A supported format's bytes cannot be decoded or opened."""


class FormatNotEnabled(FormatMismatch):
    """Docling can read the format, but this installation lacks what its reader needs."""

    def __init__(self, missing: list[str] | tuple[str, ...] = ()):
        super().__init__(NOT_ENABLED_MESSAGE)
        self.missing = tuple(missing)


def _legacy_declared_format(filename: str, mime_type: str) -> SourceFormat:
    # WP106 öncesi declared_format gövdesi; ilk altı uzantı için aynen kullanılıyor.
    try:
        extension = Path(filename).suffix.lower().lstrip(".")
        source_format = SourceFormat("jpeg" if extension == "jpg" else extension)
    except ValueError as exc:
        raise FormatMismatch("unsupported file extension") from exc
    if mime_type not in (MIME_TYPES[source_format], "application/octet-stream"):
        raise FormatMismatch("MIME type and extension disagree")
    return source_format


def matched_extension(filename: str) -> str | None:
    """The accepted extension a filename ends with (compound ones such as tar.gz first)."""
    name = filename.lower()
    for extension, _ in extension_index():
        if name.endswith("." + extension) and len(name) > len(extension) + 1:
            return extension
    return None


def format_for_filename(filename: str) -> SourceFormat:
    extension = matched_extension(filename)
    if extension is None:
        raise FormatMismatch("unsupported file extension")
    return SourceFormat(dict(extension_index())[extension])


def mime_for_filename(filename: str) -> str:
    """The MIME type Docgrain sends when it registers a file itself (CLI)."""
    source_format = format_for_filename(filename)
    if source_format in MIME_TYPES:
        return MIME_TYPES[source_format]
    mimes = SPECS[source_format.value].mime_types
    return EXTENSION_MIME.get(matched_extension(filename) or "") or (mimes[0] if mimes else "application/octet-stream")


def accepted_mime_types(source_format: SourceFormat) -> tuple[str, ...]:
    spec = SPECS[source_format.value]
    return spec.mime_types + BROWSER_MIME_ALIASES.get(source_format.value, ()) + ("application/octet-stream",)


def declared_format(filename: str, mime_type: str) -> SourceFormat:
    if Path(filename).suffix.lower().lstrip(".") in _ORIGINAL_EXTENSIONS:
        return _legacy_declared_format(filename, mime_type)
    source_format = format_for_filename(filename)
    mime = (mime_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if mime not in accepted_mime_types(source_format):
        raise FormatMismatch("MIME type and extension disagree")
    return source_format


def storage_suffix(filename: str, source_format: SourceFormat) -> str:
    """Suffix of the worker's temporary copy. Docling detects new formats by it (eml vs msg, dclg)."""
    if source_format.value in ORIGINAL_FORMATS:
        return source_format.value
    return matched_extension(filename) or source_format.value


def requirements(source_format: SourceFormat) -> tuple[str, ...]:
    return SPECS[source_format.value].requirements


def missing_requirements(source_format: SourceFormat, available: dict[str, bool]) -> list[str]:
    return [name for name in requirements(source_format)
            if name in NEVER_AVAILABLE or not available.get(name, False)]


def ensure_enabled(source_format: SourceFormat, available: dict[str, bool]) -> None:
    missing = missing_requirements(source_format, available)
    if missing:
        raise FormatNotEnabled(missing)


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
    elif source_format in (SourceFormat.PNG, SourceFormat.JPEG):
        from PIL import Image, UnidentifiedImageError

        signature = b"\x89PNG\r\n\x1a\n" if source_format is SourceFormat.PNG else b"\xff\xd8\xff"
        if not data.startswith(signature):
            raise FormatMismatch("image signature does not match extension")
        try:
            with Image.open(BytesIO(data)) as image:
                if image.format != ("PNG" if source_format is SourceFormat.PNG else "JPEG"):
                    raise FormatMismatch("decoded image format does not match extension")
                if getattr(image, "n_frames", 1) != 1:
                    raise FormatMismatch("animated images are not supported")
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
            raise CorruptSource("image cannot be safely decoded") from exc
    elif source_format is not SourceFormat.TXT:
        # WP106: every other Docling format is checked by its content, not by its name.
        _verify_docling_format(data, source_format)
    else:
        if b"\x00" in data:
            raise FormatMismatch("binary content is not TXT")
        try:
            data.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise CorruptSource("TXT is not valid UTF-8") from exc


# --- WP106 content sniffing ----------------------------------------------------------------

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_OLE_STREAMS = {
    "doc": ("WordDocument",),
    "ppt": ("PowerPoint Document",),
    "xls": ("Workbook", "Book"),
    "email": ("__substg1.0_",),
}
_OOXML_MAIN = {"docx": "word/document.xml", "pptx": "ppt/presentation.xml"}
_ODF_MIMES = {
    "odt": ("application/vnd.oasis.opendocument.text", "application/vnd.oasis.opendocument.text-template"),
    "ods": ("application/vnd.oasis.opendocument.spreadsheet", "application/vnd.oasis.opendocument.spreadsheet-template"),
    "odp": ("application/vnd.oasis.opendocument.presentation", "application/vnd.oasis.opendocument.presentation-template"),
    "epub": ("application/epub+zip",),
}
_PIL_FORMATS = {"tiff": "TIFF", "bmp": "BMP", "webp": "WEBP"}
_IMAGE_SIGNATURES = {"tiff": (b"II*\x00", b"MM\x00*"), "bmp": (b"BM",)}
_EMAIL_HEADER = re.compile(
    rb"^(from|to|subject|date|received|return-path|message-id|mime-version|delivered-to)[ \t]*:", re.IGNORECASE | re.MULTILINE)


def _text(data: bytes, name: str) -> str:
    if b"\x00" in data[:8192]:
        raise FormatMismatch(f"binary content is not {name}")
    try:
        return data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        # Docling decodes these readers itself; Latin-1/Windows-1254 text is still text.
        return data.decode("latin-1")


def _zip_names(data: bytes) -> tuple[ZipFile, set[str]]:
    if not data.startswith(b"PK"):
        raise FormatMismatch("ZIP signature does not match extension")
    try:
        package = ZipFile(BytesIO(data))
        return package, set(package.namelist())
    except BadZipFile as exc:
        raise CorruptSource("invalid ZIP package") from exc


def _check_zip(package: ZipFile) -> None:
    try:
        if package.testzip() is not None:
            raise CorruptSource("ZIP package contains a damaged entry")
    except BadZipFile as exc:
        raise CorruptSource("invalid ZIP package") from exc


def resolve_xml(data: bytes) -> SourceFormat:
    """Docling 2.130's own XML rules (datamodel/document.py: _guess_from_content, doclang root)."""
    head = data[:8192].decode("utf-8", errors="replace").lstrip("﻿")
    head = re.sub(r"<!--(.*?)-->", "", head, flags=re.DOTALL).lstrip()
    if not head.startswith("<"):
        raise FormatMismatch("XML content does not start with markup")
    if "http://www.xbrl.org/2003/instance" in head and "<xbrl" in head.lower():
        return SourceFormat.XML_XBRL
    doctype = re.search(r"<!DOCTYPE [^>]+>", head)
    if doctype:
        text = doctype.group()
        if any(item in text.lower() for item in ("us-patent-application-v4", "us-patent-grant-v4", "us-grant-025",
                                                   "patent-application-publication")):
            return SourceFormat.XML_USPTO
        if "JATS-journalpublishing" in text or "JATS-archive" in text:
            return SourceFormat.XML_JATS
    without_declaration = re.sub(r"<\?xml[^>]*\?>", "", head, count=1).lstrip()
    if re.match(r"<\s*doclang\b", without_declaration, re.IGNORECASE):
        return SourceFormat.XML_DOCLANG
    raise FormatMismatch("XML type is not one Docling reads (USPTO, JATS, XBRL or DocLang)")


def resolve_format(data: bytes, source_format: SourceFormat) -> SourceFormat:
    """A declared generic ".xml" becomes the XML format Docling would detect; others are unchanged."""
    return resolve_xml(data) if source_format is SourceFormat.XML else source_format


def _verify_image(data: bytes, value: str) -> None:
    from PIL import Image, UnidentifiedImageError

    if value == "webp":
        if not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
            raise FormatMismatch("image signature does not match extension")
    elif not data.startswith(_IMAGE_SIGNATURES[value]):
        raise FormatMismatch("image signature does not match extension")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != _PIL_FORMATS[value]:
                raise FormatMismatch("decoded image format does not match extension")
            frames = getattr(image, "n_frames", 1)
            if frames != 1 and value != "tiff":
                raise FormatMismatch("animated images are not supported")
            if frames > 500:
                raise CorruptSource("too many image pages")
            for index in range(frames):
                image.seek(index)
                image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, EOFError, Image.DecompressionBombError) as exc:
        raise CorruptSource("image cannot be safely decoded") from exc


def _verify_media(data: bytes, value: str) -> None:
    head = data[:64]
    riff = head[:4] == b"RIFF"
    ftyp = head[4:8] == b"ftyp"
    if value == "audio":
        ok = ((riff and head[8:12] == b"WAVE") or head.startswith((b"ID3", b"OggS", b"fLaC")) or ftyp
              or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0))
    else:
        ok = (ftyp or (riff and head[8:12] == b"AVI ") or head.startswith(b"\x1a\x45\xdf\xa3")
              or head[4:8] in (b"moov", b"mdat", b"wide", b"free"))
    if not ok:
        raise FormatMismatch(f"{value} signature does not match extension")


def _verify_docling_format(data: bytes, source_format: SourceFormat) -> None:
    value = source_format.value
    if not data:
        raise CorruptSource("file is empty")
    if source_format in IMAGE_FORMATS:
        _verify_image(data, value)
    elif value in ("doc", "ppt", "xls"):
        if not data.startswith(_OLE):
            raise FormatMismatch("legacy Office signature does not match extension")
        if not any(name.encode("utf-16-le") in data for name in _OLE_STREAMS[value]):
            raise FormatMismatch("legacy Office file type does not match extension")
    elif value == "email":
        if data.startswith(_OLE):
            if _OLE_STREAMS["email"][0].encode("utf-16-le") not in data:
                raise FormatMismatch("Outlook message signature does not match extension")
        else:
            _text(data[:65536], "e-mail")
            if not _EMAIL_HEADER.search(data[:65536]):
                raise FormatMismatch("e-mail headers not found")
    elif value == "rtf":
        if not data.removeprefix(b"\xef\xbb\xbf").startswith(b"{\\rtf"):
            raise FormatMismatch("RTF signature does not match extension")
    elif value in _OOXML_MAIN:
        package, names = _zip_names(data)
        with package:
            if "[Content_Types].xml" not in names or _OOXML_MAIN[value] not in names:
                raise FormatMismatch("OOXML package type does not match extension")
            _check_zip(package)
    elif value in _ODF_MIMES:
        package, names = _zip_names(data)
        with package:
            mimetype = package.read("mimetype").decode("ascii", "ignore").strip() if "mimetype" in names else ""
            if mimetype not in _ODF_MIMES[value]:
                raise FormatMismatch("OpenDocument/EPUB type does not match extension")
            _check_zip(package)
    elif value == "iwork_pages":
        package, names = _zip_names(data)
        with package:
            if not any(n.startswith("Index/") for n in names) and not names & {"index.xml", "index.xml.gz"}:
                raise FormatMismatch("Pages document index not found")
            _check_zip(package)
    elif value == "dclx":
        package, _ = _zip_names(data)
        with package:
            _check_zip(package)
    elif value == "mets_gbs":
        if not data.startswith(b"\x1f\x8b"):
            raise FormatMismatch("gzip signature does not match extension")
        found = False
        try:
            with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as archive:
                for count, member in enumerate(archive):
                    if count > 100_000:
                        raise CorruptSource("archive has too many members")
                    if member.isfile() and member.name.endswith(".xml") and member.size <= 50_000_000:
                        handle = archive.extractfile(member)
                        if handle is not None and b"http://www.loc.gov/METS/" in handle.read():
                            found = True
                            break
        except (tarfile.TarError, EOFError, OSError) as exc:
            raise CorruptSource("invalid METS archive") from exc
        if not found:
            raise FormatMismatch("METS document not found in archive")
    elif value in ("json_docling", "boxnote"):
        try:
            document = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise CorruptSource("JSON cannot be decoded") from exc
        if value == "json_docling" and not (isinstance(document, dict)
                                            and document.get("schema_name") == "DoclingDocument"):
            raise FormatMismatch("JSON is not a Docling document")
        if value == "boxnote" and not (isinstance(document, dict) and isinstance(document.get("doc"), dict)):
            raise FormatMismatch("JSON is not a Box Note")
    elif value == "xml" or source_format in XML_FORMATS:
        resolved = resolve_xml(data)
        if value != "xml" and resolved is not source_format:
            raise FormatMismatch("XML type does not match extension")
    elif value in ("html", "mhtml"):
        text = _text(data, value).lstrip("﻿")
        lower = re.sub(r"<!--(.*?)-->", "", text[:65536].lower(), flags=re.DOTALL).lstrip()
        if value == "mhtml":
            if "multipart/related" not in lower:
                raise FormatMismatch("MHTML archive header not found")
        elif not re.search(r"<!doctype\s+html|<html|<head|<body", lower):
            raise FormatMismatch("HTML markup not found")
    elif value == "vtt":
        if not _text(data, value).lstrip("﻿").startswith("WEBVTT"):
            raise FormatMismatch("WebVTT header not found")
    elif value == "csv":
        sample = _text(data, value)[:8192]
        if "\n" in sample.strip():
            try:
                csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error as exc:
                raise FormatMismatch("CSV delimiter not found") from exc
    elif value in ("md", "asciidoc", "latex"):
        _text(data, value)
    elif value == "afp":
        # Docling's _detect_afp: X'5A' carriage control, a sane field length, then X'D3'.
        length = int.from_bytes(data[1:3], "big") if len(data) >= 9 else 0
        if not (data[:1] == b"\x5a" and 8 <= length <= 32767 and data[3] == 0xD3):
            raise FormatMismatch("AFP structured field not found")
    elif value in ("audio", "video"):
        _verify_media(data, value)
    elif value == "ebcdic":
        return  # Records carry no signature; the format stays closed (docling_formats.REQUIREMENTS).
    else:
        raise FormatMismatch("unsupported file format")
