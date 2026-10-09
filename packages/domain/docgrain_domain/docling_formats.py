"""The one mapping from Docling's input formats to Docgrain's accepted files.

The API and the CLI do not install Docling, so the three Docling tables are kept here as a
snapshot of ``docling==2.130.0``:

- ``docling.datamodel.base_models.InputFormat`` (keys, in enum order),
- ``FormatToExtensions`` (first tuple) and ``FormatToMimeType`` (second tuple).

The worker image compares this snapshot with the installed Docling at startup and in
``tests/integration/test_wp106_docling_formats.py``; regenerate it with
``python -m docgrain_worker.format_capabilities --snapshot`` inside the worker image.
Everything else here (accepted extensions, MIME types, requirements, the web list) is
derived from the snapshot; only Docgrain's own decisions are written by hand and named.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

DOCLING_VERSION = "2.130.0"

DOCLING_INPUT_FORMATS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "docx": (("docx", "dotx", "docm", "dotm"), ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.wordprocessingml.template")),
    "doc": (("doc", "dot"), ("application/msword", "application/x-msword")),
    "rtf": (("rtf",), ("application/rtf", "text/rtf", "application/x-rtf")),
    "pptx": (("pptx", "potx", "ppsx", "pptm", "potm", "ppsm"), ("application/vnd.openxmlformats-officedocument.presentationml.template", "application/vnd.openxmlformats-officedocument.presentationml.slideshow", "application/vnd.openxmlformats-officedocument.presentationml.presentation")),
    "ppt": (("ppt", "pot", "pps"), ("application/vnd.ms-powerpoint",)),
    "html": (("html", "htm", "xhtml"), ("text/html", "application/xhtml+xml")),
    "mhtml": (("mhtml", "mht"), ("application/x-mimearchive", "multipart/related")),
    "image": (("jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp"), ("image/png", "image/jpeg", "image/tiff", "image/gif", "image/bmp", "image/webp")),
    "pdf": (("pdf",), ("application/pdf",)),
    "asciidoc": (("adoc", "asciidoc", "asc"), ("text/asciidoc",)),
    "md": (("md", "markdown", "txt", "text", "qmd", "rmd", "Rmd"), ("text/markdown", "text/x-markdown", "text/plain")),
    "csv": (("csv",), ("text/csv",)),
    "xlsx": (("xlsx", "xlsm", "xltx", "xltm"), ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",)),
    "xls": (("xls", "xlt"), ("application/vnd.ms-excel", "application/x-msexcel")),
    "odt": (("odt", "ott"), ("application/vnd.oasis.opendocument.text", "application/vnd.oasis.opendocument.text-template")),
    "ods": (("ods", "ots"), ("application/vnd.oasis.opendocument.spreadsheet", "application/vnd.oasis.opendocument.spreadsheet-template")),
    "odp": (("odp", "otp"), ("application/vnd.oasis.opendocument.presentation", "application/vnd.oasis.opendocument.presentation-template")),
    "xml_uspto": (("xml", "txt"), ("application/xml", "text/plain")),
    "xml_jats": (("xml", "nxml"), ("application/xml",)),
    "xml_xbrl": (("xml", "xbrl"), ("application/xml", "application/xhtml+xml")),
    "xml_doclang": (("dclg", "dclg.xml"), ("application/xml",)),
    "dclx": (("dclx",), ()),
    "mets_gbs": (("tar.gz",), ("application/mets+xml",)),
    "json_docling": (("json",), ("application/json",)),
    "audio": (("wav", "mp3", "m4a", "aac", "ogg", "flac"), ("audio/x-wav", "audio/mpeg", "audio/wav", "audio/mp3", "audio/mp4", "audio/m4a", "audio/aac", "audio/ogg", "audio/flac", "audio/x-flac")),
    "video": (("mp4", "avi", "mov", "mkv", "webm"), ("video/mp4", "video/avi", "video/x-msvideo", "video/quicktime", "video/x-matroska", "video/webm")),
    "vtt": (("vtt",), ("text/vtt",)),
    "latex": (("tex", "latex"), ("text/x-tex", "application/x-tex", "text/x-latex")),
    "email": (("eml", "msg"), ("message/rfc822", "application/vnd.ms-outlook")),
    "epub": (("epub",), ("application/epub+zip",)),
    "boxnote": (("boxnote",), ("application/vnd.box.boxnote",)),
    "iwork_pages": (("pages",), ("application/vnd.apple.pages", "application/x-iwork-pages-sffpages")),
    "ebcdic": (("ebc", "ebcdic"), ("application/x-ebcdic",)),
    "afp": (("afp",), ("application/vnd.ibm.modcap", "application/x-afp")),
}

# --- Docgrain decisions (hand-written, each one named) -------------------------------------

# The six formats accepted before WP106. Their SourceFormat values are stored data and never change.
ORIGINAL_FORMATS = ("pdf", "docx", "txt", "xlsx", "png", "jpeg")

# Images keep Docgrain's image rules per file type (decoded, EXIF-aware, full-page OCR), so the
# single Docling IMAGE format becomes one SourceFormat per image type. jpg/tif are aliases.
IMAGE_TYPES = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "tif": "tiff", "tiff": "tiff", "bmp": "bmp", "webp": "webp"}

# TXT keeps Docgrain's exact-text reader (it keeps 100 % of words), so plain-text extensions of
# Docling's MD and XML_USPTO formats stay TXT. USPTO "PATN" text files are therefore read as text.
OWN_TEXT_EXTENSIONS = ("txt", "text")

# One ".xml" file can be USPTO, JATS, XBRL or DocLang. It is accepted as "xml" and resolved from its
# content with Docling's own rules (source_format.resolve_format); other extensions are specific.
XML_FAMILY = ("xml_uspto", "xml_jats", "xml_xbrl", "xml_doclang")

# What a format needs beyond the base worker image. The worker probes each requirement at startup
# (docgrain_worker.format_capabilities) and the API rejects formats whose requirement is missing.
REQUIREMENTS: dict[str, tuple[str, ...]] = {
    # MsWord/MsPowerpoint/MsExcel backends call LibreOffice (`soffice`) to convert legacy files.
    "doc": ("libreoffice",), "rtf": ("libreoffice",), "ppt": ("libreoffice",), "xls": ("libreoffice",),
    # OpenDocument backends import `odfdo` (docling-slim[format-opendocument]).
    "odt": ("odfdo",), "ods": ("odfdo",), "odp": ("odfdo",),
    # XBRLDocumentBackend imports `arelle` (docling-slim[format-xml-xbrl]).
    "xml_xbrl": ("arelle",),
    # AsrPipeline / VideoPipeline: ffmpeg binary + openai-whisper + baked Whisper weights, and a
    # Docgrain reading profile that passes the offline model directory (not wired yet).
    "audio": ("ffmpeg", "openai-whisper", "asr-profile"),
    "video": ("ffmpeg", "openai-whisper", "asr-profile"),
    # METS/GBS runs StandardPdfPipeline; it needs Docgrain's pinned layout models wired in.
    "mets_gbs": ("mets-profile",),
    # EBCDIC records are meaningless without the COBOL copybook of each file; uploads carry none.
    "ebcdic": ("ebcdic-layout",),
}
# Formats added by a later Docling release stay closed until someone checks their backend.
UNVERIFIED = ("unverified-docling-format",)
NEVER_AVAILABLE = frozenset({"ebcdic-layout", "unverified-docling-format"})

NOT_ENABLED_MESSAGE = "Bu dosya türü bu kurulumda henüz açık değil."
# The worker writes its probed requirements here at startup; the API reads it before accepting uploads.
CAPABILITIES_OBJECT = "system/worker-capabilities.json"

# MIME types browsers and mail tools send for these files although Docling does not list them.
BROWSER_MIME_ALIASES: dict[str, tuple[str, ...]] = {
    "docx": ("application/vnd.ms-word.document.macroenabled.12", "application/vnd.ms-word.template.macroenabled.12"),
    "xlsx": ("application/vnd.ms-excel.sheet.macroenabled.12", "application/vnd.openxmlformats-officedocument.spreadsheetml.template",
             "application/vnd.ms-excel.template.macroenabled.12"),
    "pptx": ("application/vnd.ms-powerpoint.presentation.macroenabled.12", "application/vnd.ms-powerpoint.slideshow.macroenabled.12",
             "application/vnd.ms-powerpoint.template.macroenabled.12"),
    "csv": ("application/vnd.ms-excel", "text/plain", "text/x-csv", "application/csv"),
    "md": ("text/plain",), "asciidoc": ("text/plain",), "latex": ("text/plain",), "vtt": ("text/plain",),
    "xml": ("text/xml",), "xml_jats": ("text/xml",), "xml_xbrl": ("text/xml",), "xml_doclang": ("text/xml",),
    "json_docling": ("text/plain",), "boxnote": ("application/json",),
    "mhtml": ("message/rfc822",), "dclx": ("application/zip",),
    "bmp": ("image/x-ms-bmp", "image/x-bmp"),
    "mets_gbs": ("application/gzip", "application/x-gzip", "application/x-compressed-tar"),
    "audio": ("audio/x-m4a", "audio/wave", "audio/vnd.wave", "audio/x-aac"),
    "video": ("video/x-m4v",),
}

# Extension-specific MIME used when Docgrain itself registers a file (CLI). First match wins.
EXTENSION_MIME = {
    "jpg": "image/jpeg", "tif": "image/tiff", "msg": "application/vnd.ms-outlook", "wav": "audio/wav",
    "mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac", "ogg": "audio/ogg", "flac": "audio/flac",
    "avi": "video/x-msvideo", "mov": "video/quicktime", "mkv": "video/x-matroska", "webm": "video/webm",
    "xhtml": "application/xhtml+xml", "xbrl": "application/xml", "dclx": "application/zip",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# Plain Turkish names for the upload copy, in display order (family -> label).
FAMILY_LABELS = (
    ("pdf", "PDF"), ("word", "Word"), ("excel", "Excel"), ("powerpoint", "PowerPoint"),
    ("opendocument", "OpenDocument"), ("text", "metin"), ("web", "web sayfası"), ("email", "e-posta"),
    ("ebook", "e-kitap"), ("subtitle", "altyazı"), ("image", "görsel"),
)
FAMILY = {
    "pdf": "pdf", "docx": "word", "doc": "word", "rtf": "word", "iwork_pages": "word", "xlsx": "excel", "xls": "excel",
    "csv": "excel", "pptx": "powerpoint", "ppt": "powerpoint", "odt": "opendocument", "ods": "opendocument",
    "odp": "opendocument", "txt": "text", "md": "text", "asciidoc": "text", "latex": "text", "boxnote": "text",
    "html": "web", "mhtml": "web", "email": "email", "epub": "ebook", "vtt": "subtitle", "png": "image",
    "jpeg": "image", "tiff": "image", "bmp": "image", "webp": "image",
}


@dataclass(frozen=True)
class FormatSpec:
    """One accepted SourceFormat value and where Docling reads it."""

    value: str
    docling_format: str | None  # InputFormat value; None for Docgrain's own TXT and the XML family
    extensions: tuple[str, ...]
    mime_types: tuple[str, ...]
    requirements: tuple[str, ...]

    @property
    def family(self) -> str | None:
        return FAMILY.get(self.value)


def _unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def derive_specs(snapshot: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = DOCLING_INPUT_FORMATS) -> dict[str, FormatSpec]:
    """Derive Docgrain's accepted formats from Docling's three tables (pure, testable)."""
    specs: dict[str, FormatSpec] = {}
    owned: set[str] = set()

    def requirement(name: str) -> tuple[str, ...]:
        return REQUIREMENTS.get(name, () if name in KNOWN_BASE_FORMATS else UNVERIFIED)

    specs["txt"] = FormatSpec("txt", None, OWN_TEXT_EXTENSIONS, ("text/plain",), ())
    owned.update(OWN_TEXT_EXTENSIONS)
    image_extensions, image_mimes = snapshot["image"]
    for extension in image_extensions:
        value = IMAGE_TYPES[extension.lower()]
        mime = f"image/{value}"
        previous = specs.get(value)
        extensions = (previous.extensions if previous else ()) + (extension.lower(),)
        specs[value] = FormatSpec(value, "image", _unique(extensions),
                                  tuple(m for m in image_mimes if m == mime), ())
        owned.add(extension.lower())
    xml_mimes: list[str] = []
    for name, (extensions, mimes) in snapshot.items():
        if name == "image":
            continue
        if name in XML_FAMILY:
            xml_mimes.extend(mimes)
        own = _unique(e.lower() for e in extensions if e.lower() not in owned and e.lower() != "xml")
        if not own and name not in XML_FAMILY:
            continue
        specs[name] = FormatSpec(name, name, own, _unique(mimes), requirement(name))
        owned.update(own)
    specs["xml"] = FormatSpec("xml", None, ("xml",), _unique(m for m in xml_mimes if m != "text/plain"), ())
    return specs


# Every Docling 2.130 format whose backend was read for WP106 and needs nothing beyond the image.
KNOWN_BASE_FORMATS = frozenset({
    "docx", "pptx", "html", "mhtml", "image", "pdf", "asciidoc", "md", "csv", "xlsx", "xml_uspto", "xml_jats",
    "xml_doclang", "dclx", "json_docling", "vtt", "latex", "email", "epub", "boxnote", "iwork_pages", "afp",
})

SPECS = derive_specs()


def extension_index() -> list[tuple[str, str]]:
    """(extension, SourceFormat value) pairs, longest extension first for compound suffixes."""
    pairs = [(extension, spec.value) for spec in SPECS.values() for extension in spec.extensions]
    return sorted(pairs, key=lambda pair: (-len(pair[0]), pair[0]))


def accepted_extensions(*, include_impossible: bool = True) -> list[str]:
    """Every extension Docgrain accepts; the web picker leaves out formats no installation can open."""
    return sorted({extension for spec in SPECS.values() for extension in spec.extensions
                   if include_impossible or not NEVER_AVAILABLE.intersection(spec.requirements)})


def upload_summary() -> str:
    """Turkish upload copy from the formats that need nothing beyond the base image."""
    families = {spec.family for spec in SPECS.values() if not spec.requirements and spec.family}
    labels = [label for family, label in FAMILY_LABELS if family in families]
    return ", ".join(labels[:-1]) + " veya " + labels[-1] if len(labels) > 1 else "".join(labels)


def typescript_module() -> str:
    """Generated apps/web/lib/source-formats.ts; tests/unit/test_wp106_formats.py keeps it in sync."""
    accept = ",".join("." + extension for extension in accepted_extensions(include_impossible=False))
    return (
        "// Generated from packages/domain/docgrain_domain/docling_formats.py — do not edit by hand.\n"
        "// Regenerate: python -m docgrain_domain.docling_formats --typescript > apps/web/lib/source-formats.ts\n"
        f"export const DOCLING_VERSION = {json.dumps(DOCLING_VERSION)};\n"
        f"export const ACCEPTED_FILE_TYPES = {json.dumps(accept)};\n"
        f"export const UPLOAD_SUMMARY = {json.dumps(upload_summary(), ensure_ascii=False)};\n"
        f"export const NOT_ENABLED_MESSAGE = {json.dumps(NOT_ENABLED_MESSAGE, ensure_ascii=False)};\n"
    )


if __name__ == "__main__":  # pragma: no cover - generator entry point
    if sys.argv[1:] == ["--typescript"]:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdout.write(typescript_module())
    else:
        print(json.dumps({value: spec.__dict__ for value, spec in SPECS.items()}, indent=2, ensure_ascii=False))
