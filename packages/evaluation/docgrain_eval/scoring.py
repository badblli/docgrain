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


LIST_FIELDS = {"bed_types", "features"}
LIST_SEPARATOR = re.compile(r"\b(?:veya|or|oder|или)\b|;|(?<!\d),|,(?!\d)")
VALUE_NUMBER = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?!\w)")
UNIT_ALIASES = {
    "m²": r"(?<![a-z])(?:m2|sqm|square metres?|square meters?|metrekare|metre kare)\b",
    "eur": r"€|\b(?:eur|euro|euros|avro)\b",
    "usd": r"\$|\b(?:usd|dollars?|dolar)\b",
    "try": r"₺|\b(?:try|tl|lira)\b",
    "person": r"\b(?:persons?|people|kisi|kisilik)\b",
    "m": r"\b(?:metres?|meters?|metre)\b",
}


def _value_text(value: str) -> str:
    text = normalize(value)
    for canonical, pattern in UNIT_ALIASES.items():
        text = re.sub(pattern, lambda _, canonical=canonical: canonical, text)
    text = re.sub(r"\b(eur|usd|try)\s*([+-]?\d+(?:[.,]\d+)*)\b", r"\2 \1", text)
    quantities = {}

    def quantity(match):
        marker = "\x00quantity" + "a" * (len(quantities) + 1) + "\x00"
        quantities[marker] = format(number(match[1]).normalize(), "f") + match[2]
        return marker

    # Decimal quantities must not become clocks (18.50 m2 is not 18:50).
    text = re.sub(r"(?<!\w)([+-]?\d+(?:[.,]\d+)*)\s*(m²|m|eur|usd|try|person)(?!\w)",
                  quantity, text)
    text = normalize_answer(text)
    # Keep all surrounding qualifiers; never compare just the first number.
    text = VALUE_NUMBER.sub(lambda m: format(number(m.group()).normalize(), "f"), text)
    for marker, canonical in quantities.items():
        text = text.replace(marker, canonical)
    return text


def list_items(value: object) -> list[str]:
    """Explicit alternatives are unordered; decimal commas are not separators."""
    values = value if isinstance(value, list) else [value]
    return sorted({part.strip() for item in values
                   for part in LIST_SEPARATOR.split(_value_text(str(item))) if part.strip()})


def normalized_value(value: object, field: str = "") -> object:
    """Comparison key only: retain source spelling, value type and exact evidence.

    Lists/string alternatives are equivalent only for list fields (or actual
    lists). Prose punctuation, currencies, negation and qualifiers are preserved.
    """
    if isinstance(value, bool) or value is None:
        return ["literal", value]
    if field in LIST_FIELDS or isinstance(value, list):
        return ["list", list_items(value)]
    if isinstance(value, (int, float)):
        return ["number", format(Decimal(str(value)).normalize(), "f")]
    if field in {"amount", "size_m2", "capacity"} and isinstance(value, str) and re.fullmatch(
            r"[+-]?\d+(?:[.,]\d+)*", value.strip()):
        return ["number", format(number(value).normalize(), "f")]
    if isinstance(value, dict):
        return ["object", {key: normalized_value(item) for key, item in sorted(value.items())}]
    text = _value_text(str(value))
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return ["number", text]
    # Adjacent spacing and unit spelling are equivalent, but units never vanish.
    text = re.sub(r"(?<=\d)\s+(?=(?:m²|m|eur|usd|try|person)\b)", "", text)
    text = re.sub(r"\b(eur|usd|try)\s*([+-]?\d+(?:\.\d+)?)\b", r"\2\1", text)
    return ["text", text]


FREE_TEXT_FIELDS = {"text", "description", "conditions", "applies_to"}
KEY_FACT_THRESHOLD = .7
# A deliberately small, reviewable vocabulary. Unknown nouns stay literal.
FACT_NOUNS = {
    "pet": r"\b(?:pets?|animals?|evcil hayvan(?:lar|lari)?|hayvan(?:lar|lari)?|haustiere?|tiere?|животные)\b",
    "smoking": r"\b(?:smoking|smoke|sigara(?: icmek| icme)?|rauchen|курение)\b",
    "room": r"\b(?:rooms?|oda(?:lar|larda)?|zimmer|номер)\b",
    "indoor": r"\b(?:indoors?|ic mekan(?:lar|larda)?|kapali alan(?:lar|larda)?)\b",
    "outdoor": r"\b(?:outdoors?|acik alan(?:lar|larda)?)\b",
    "assistance": r"\b(?:assistance|service(?=\s+dogs?)|rehber|yardimci|assistenz)\b",
    "dog": r"\b(?:dogs?|kopek(?:ler|leri)?|hunde?)\b",
    "child": r"\b(?:children|child|kids?|cocuk(?:lar|lari)?|kinder)\b",
    "reservation": r"\b(?:reservations?|booking|rezervasyon|reservierung)\b",
    "parking": r"\b(?:parking|otopark|parkplatz)\b",
    "wifi": r"\b(?:wi-fi|wi fi|wifi|wlan)\b",
    "checkout": r"\b(?:check-out|check out|checkout|cikis)\b",
    "late": r"\b(?:late|gec|spat)\b",
    "free": r"\b(?:free|ucretsiz|kostenlos)\b",
    "paid": r"\b(?:paid|chargeable|ucretli|kostenpflichtig)\b",
}
NEGATION = re.compile(
    r"\b(?:no|not|never|without|prohibited|forbidden|nicht|kein\w*|verboten|нет|не|"
    r"yasak\w*|yok\w*|haric|edilmez|edilmem\w*|verilmez|verilmem\w*|alinmaz|"
    r"[a-z]+(?:ilmez|ilmemektedir|ilemez|ulmaz|unmaz|anmaz|enmez|maz|mez))\b")
EXCEPTION = re.compile(r"\b(?:except|exception\w*|unless|excluding|haric|istisna\w*|ausser)\b")
FACT_STOPWORDS = {
    "a", "an", "the", "is", "are", "be", "to", "of", "for", "in", "on", "at", "and", "or",
    "with", "as", "it", "its", "this", "that", "all", "only", "may", "can", "must",
    "will", "per", "until", "up", "by", "from", "available", "availability",
    "accepted", "accept", "allowed", "allow", "admitted", "permitted", "permit",
    "prohibited", "forbidden", "strictly", "policy", "policies", "except",
    "exceptions", "exception", "without", "no", "not", "never", "unless", "excluding",
    "cannot", "ve", "veya", "ile", "bir", "bu", "icin", "kadar", "olarak", "olan",
    "tum", "sadece", "kabul", "edilir", "edilmektedir", "izin", "verilir", "yasak",
    "mevcuttur", "mevcut", "vardir", "bulunur", "sunulur", "politikasi", "politikalar",
    "icilmesi", "icmek", "icme", "tesiste", "tesis", "kabulune", "evcil", "haric",
    "istisna", "nicht", "kein", "keine", "erlaubt", "akzeptiert", "werden",
    "wird", "ist", "sind", "die", "der", "das", "und", "oder", "im", "ausser",
}


def key_facts(value: str) -> tuple[set[str], set[str]]:
    """Noun overlap plus exact critical facts; no substring acceptance of prose."""
    text = _value_text(value)
    critical = {"time:" + m.group() for m in TIME.finditer(text)}
    without_times = TIME.sub(" ", text)
    critical.update("number:" + m.group() for m in VALUE_NUMBER.finditer(without_times))
    for name in UNIT_ALIASES:
        if re.search(rf"(?<![a-z]){re.escape(name)}(?!\w)", text):
            critical.add("unit:" + name)
    critical.update("quantity:" + m.group() for m in re.finditer(
        r"[+-]?\d+(?:\.\d+)?(?:m²|m|eur|usd|try|person)(?!\w)", text))
    if NEGATION.search(text):
        critical.add("negation")
    if EXCEPTION.search(text):
        critical.add("exception")
    # Keep range direction and comparison operators meaningful.
    critical.update("range:" + m.group() for m in re.finditer(
        r"\d+(?::\d+)?-\d+(?::\d+)?|[<>]=?\s*\d+", text))
    for noun, pattern in FACT_NOUNS.items():
        text = re.sub(pattern, lambda _, noun=noun: noun, text)
    # Negation must stay attached to its topic, including multi-rule prose.
    subjects = {"pet", "smoking", "reservation", "parking", "wifi", "checkout", "child", "dog"}
    for clause in re.split(r"[;.!?]|\b(?:but|however|ancak|ama)\b", text):
        topic = subjects & set(re.findall(r"\w+", EXCEPTION.split(clause)[0]))
        if NEGATION.search(clause):
            critical.update("negative:" + noun for noun in topic)
        # Associate numbers/prices with each topic to catch swapped price pairs.
        if topic:
            for literal in re.findall(r"\d+(?::\d+)?(?:eur|usd|try|m²|person)?", clause):
                critical.update("topic:" + noun + ":" + literal for noun in topic)
    words = {word for word in re.findall(r"[^\W\d_]+", text)
             if (word not in FACT_STOPWORDS and word not in UNIT_ALIASES and len(word) > 1
                 and not NEGATION.fullmatch(word))}
    return words, critical


def key_fact_overlap(actual: str, expected: str) -> float:
    """Symmetric noun overlap; differing critical facts always score zero."""
    predicted, predicted_critical = key_facts(actual)
    target, target_critical = key_facts(expected)
    if predicted_critical != target_critical:
        return 0.0
    if not predicted or not target:
        return float(_value_text(actual) == _value_text(expected))
    return len(predicted & target) / max(len(predicted), len(target))


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
