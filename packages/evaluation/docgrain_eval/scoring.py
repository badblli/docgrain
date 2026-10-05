"""Deterministic answer and citation scoring."""

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .golden import ConflictExpected, NumberExpected, Question


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.replace("ı", "i").split())


TIME = re.compile(r"(?<!\w)(\d{1,2})[:.](\d{2})(?!\w)")
RANGE_SEPARATOR = r"(?:[-–—]|\b(?:ile|ila|to)\b)"


def _clock(match: re.Match) -> str:
    hour, minute = map(int, match.groups())
    if hour == 24 and minute == 0:
        hour = 0
    if hour > 23 or minute > 59:
        return match.group()
    return f"{hour:02d}:{minute:02d}"


def normalize_answer(value: object) -> str:
    text = TIME.sub(_clock, normalize(value))
    # Only numeric ranges: words such as Wi-Fi must keep their original meaning.
    return re.sub(rf"(?<=\d)\s*{RANGE_SEPARATOR}\s*(?=\d)", "-", text)


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


def _answer_number(answer: object, expected_unit: str | None) -> tuple[Decimal | None, str | None]:
    text = normalize(answer)
    candidates = []
    for match in NUMBER.finditer(text):
        value = number(match.group())
        if value is None:
            continue
        adjacent = re.match(
            r"\s*(m²|m2|metrekare|metre kare|€|eur|euro|avro|kişi|kisi|person|m|metre)(?=\W|$)",
            text[match.end():],
        )
        candidate_unit = unit(adjacent.group(1)) if adjacent else None
        candidates.append((match, value, candidate_unit))
    if not candidates:
        return None, None
    totals = list(re.finditer(r"\b(?:toplam|total)\b", text))
    if totals:
        chosen = min(candidates, key=lambda item: min(
            min(abs(item[0].start() - marker.end()), abs(item[0].end() - marker.start()))
            for marker in totals
        ))
    else:
        chosen = next((item for item in candidates if item[2] == expected_unit), candidates[0])
    return chosen[1], chosen[2]


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
    if isinstance(value, dict):
        open_keys = {"open", "opening", "opening_time", "open_time", "start", "start_time"}
        close_keys = {"close", "closing", "closing_time", "close_time", "end", "end_time"}
        opening = [v for k, v in value.items() if normalize(k) in open_keys]
        closing = [v for k, v in value.items() if normalize(k) in close_keys]
        if len(opening) != 1 or len(closing) != 1:
            return None
        value = f"{opening[0]}-{closing[0]}"
    match = re.search(r"\b(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})\b", normalize_answer(value))
    if not match:
        return None
    h1, m1, h2, m2 = map(int, match.groups())
    if max(h1, h2) > 23 or max(m1, m2) > 59:
        return None
    return f"{h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}"


def _number_correct(expected: NumberExpected, parsed: dict) -> bool:
    candidate = parsed.get("value")
    candidate_unit = parsed.get("unit")
    expected_unit = unit(expected.unit or "")
    if isinstance(candidate, dict):
        candidate_unit = candidate.get("unit") or candidate_unit
        preferred = next((candidate[key] for key in ("value", "amount")
                          if number(candidate.get(key)) is not None), None)
        numeric = [v for k, v in candidate.items() if k != "unit"
                   and isinstance(v, (int, float, str)) and not isinstance(v, bool)
                   and number(v) is not None]
        candidate = preferred if preferred is not None else numeric[0] if len(numeric) == 1 else None
    if number(candidate) is None:
        candidate, answer_unit = _answer_number(parsed.get("answer", ""), expected_unit)
        candidate_unit = candidate_unit or answer_unit
    candidate_unit = candidate_unit or unit(candidate) or unit(parsed.get("answer", ""))
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
    answer = normalize_answer(parsed.get("answer") or parsed.get("value") or "")
    if isinstance(expected, list) and expected and isinstance(expected[0], ConflictExpected):
        return all(normalize_answer(item.value) in answer for item in expected)
    if question.answer_type == "number":
        return _number_correct(expected, parsed)
    if question.answer_type == "time_range":
        candidate = time_range(parsed.get("value")) or time_range(parsed.get("answer"))
        return candidate is not None and candidate == time_range(expected)
    if question.answer_type == "list":
        return all(normalize_answer(item) in answer for item in expected)
    return any(normalize_answer(item) in answer for item in [expected, *question.accept] if item)


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


def rescore(args):
    """Re-score stored responses without constructing an API or model client."""
    from .cli import _write_json, _write_jsonl, summarize
    from .golden import load_jsonl

    directory = Path(args.run_dir)
    questions = {question.id: question for question in load_jsonl(args.questions, Question)}
    rows = [json.loads(line) for line in (directory / "results.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    seen = set()
    for row in rows:
        question_id = row["id"]
        if question_id in seen:
            raise ValueError(f"duplicate result id: {question_id}")
        if question_id not in questions:
            raise ValueError(f"unknown question id: {question_id}")
        seen.add(question_id)
        question = questions[question_id]
        parsed = row["parsed"]
        if parsed is not None and not isinstance(parsed, dict):
            raise ValueError(f"parsed response must be an object or null: {question_id}")
        row["correct"] = correct(question, parsed)
        row["answer_type"] = question.answer_type
        row["document_ids"] = question.document_ids
        row["categories"] = [question.category]
        row["difficulties"] = [question.difficulty]
        row["abstained"] = parsed.get("abstained") is True if parsed else False
        row["citation_hit"], row["page_hit"] = citation(question, parsed)
    original = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    summary = summarize(rows, "", original["revisions"], original["model"])
    for key in ("context_characters", "context_tokens_approx"):
        summary[key] = original[key]
    out = directory / "rescored"
    out.mkdir(exist_ok=True)
    _write_jsonl(out / "results.jsonl", rows)
    _write_json(out / "summary.json", summary)
    overall = summary["overall"]
    accuracy = f"{overall['accuracy']:.1%}" if overall["accuracy"] is not None else "—"
    (out / "summary.md").write_text(
        "# Yeniden değerlendirme\n\n"
        f"Doğruluk: {overall['correct']}/{overall['count']} ({accuracy})\n\n"
        "Saklanan yanıtlar kullanıldı; model çağrısı yapılmadı.\n\n"
        "```json\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n```\n",
        encoding="utf-8")
    print(f"rescored: {overall['correct']}/{overall['count']} ({accuracy})")
