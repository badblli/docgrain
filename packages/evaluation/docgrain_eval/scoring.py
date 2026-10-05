"""Deterministic answer and citation scoring."""

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from .golden import ConflictExpected, NumberExpected, Question


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.replace("ı", "i").split())


def parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise TypeError("model response must be an object")
    return value


NUMBER = re.compile(r"[-+]?\d[\d.,\s]*")


def number(value: object) -> Decimal | None:
    match = NUMBER.search(str(value))
    if not match:
        return None
    text = match.group().replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1 or re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def unit(value: object) -> str | None:
    text = normalize(value)
    if re.search(r"(?:m²|m2|metrekare|metre kare)", text):
        return "m²"
    if re.search(r"(?:€|\beur\b|\beuro\b|\bavro\b)", text):
        return "€"
    if re.search(r"\b(?:kişi|kisi|person)\b", text):
        return "kişi"
    if re.search(r"\b(?:m|metre)\b", text):
        return "m"
    return None


def time_range(value: object) -> str | None:
    match = re.search(r"\b(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})\b", str(value))
    if not match:
        return None
    h1, m1, h2, m2 = map(int, match.groups())
    if max(h1, h2) > 23 or max(m1, m2) > 59:
        return None
    return f"{h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}"


def _number_correct(expected: NumberExpected, parsed: dict) -> bool:
    candidate = parsed.get("value")
    if candidate is None:
        candidate = parsed.get("answer", "")
    if isinstance(candidate, dict):
        candidate_unit = candidate.get("unit")
        candidate = candidate.get("value", "")
    else:
        candidate_unit = parsed.get("unit") or unit(candidate) or unit(parsed.get("answer", ""))
    expected_unit = unit(expected.unit or "")
    if expected_unit and candidate_unit and unit(candidate_unit) != expected_unit:
        return False
    return number(candidate) == number(expected.value)


def correct(question: Question, parsed: dict | None) -> bool:
    if parsed is None:
        return False
    abstained = parsed.get("abstained") is True
    if question.answer_type == "unanswerable":
        return abstained
    if abstained:
        return False
    expected = question.expected
    answer = normalize(parsed.get("answer") or parsed.get("value") or "")
    if isinstance(expected, list) and expected and isinstance(expected[0], ConflictExpected):
        return all(normalize(item.value) in answer for item in expected)
    if question.answer_type == "number":
        return _number_correct(expected, parsed)
    if question.answer_type == "time_range":
        return time_range(parsed.get("value") or parsed.get("answer")) == time_range(expected)
    if question.answer_type == "list":
        return all(normalize(item) in answer for item in expected)
    return any(normalize(item) in answer for item in [expected, *question.accept] if item)


def citation(question: Question, parsed: dict | None) -> tuple[bool | None, bool | None]:
    if not question.evidence:
        return None, None
    citations = parsed.get("citations", []) if parsed else []
    if not isinstance(citations, list):
        citations = []
    document_hit = any(
        isinstance(c, dict) and c.get("document_id") == e.document_id
        for c in citations for e in question.evidence
    )
    paged = [e for e in question.evidence if e.page is not None]
    page_hit = None if not paged else any(
        isinstance(c, dict) and c.get("document_id") == e.document_id
        and str(e.page) in str(c.get("locator", ""))
        for c in citations for e in paged
    )
    return document_hit, page_hit
