"""Conservative, offline cardinality rules shared by review and publication."""

import json
import re
from datetime import date
from typing import get_args, get_origin

from .extractor import normalize_quote
from .merge_models import FactCandidate, VersionedEvidence


def list_field(runtime, kind, field):
    fact = get_args(runtime.models[kind][1].model_fields[field].annotation)[0]
    return get_origin(fact.model_fields["value"].annotation) is list


def _date(value):
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        match = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", value.strip())
        if not match:
            return False
        try:
            day, month, year = map(int, match.groups())
            date(year, month, day)
            return True
        except ValueError:
            return False


def _time(value):
    return isinstance(value, str) and bool(re.fullmatch(
        r"(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[-–]\s*(?:[01]?\d|2[0-3]):[0-5]\d)?",
        value.strip()))


def _price_variant(candidate):
    labels = set()
    value = candidate.value
    texts = [value] if isinstance(value, str) else [e.quote for e in candidate.evidence]
    for text in texts:
        match = re.fullmatch(r"([^:\d]+):\s*(\d+(?:[.,]\d+)?)\s+([A-Z]{3})", text.strip())
        if not match:
            return None
        if not isinstance(value, str) and (
                type(value) not in (int, float) or float(match.group(2).replace(",", ".")) != value):
            return None
        labels.add(match.group(1).strip().casefold())
    return next(iter(labels)) if len(labels) == 1 else None


def multiple_values(runtime, record, field, merged, lang, candidates):
    if lang in merged.multi_value_languages or list_field(runtime, record.type, field):
        return True
    if len(candidates) < 2 or field == runtime.identities[record.type]:
        return False
    # A locator can identify an entire table. Shared locators are safe for dates
    # and times only when each candidate quotes its own distinct value exactly.
    # Every candidate must be cited by the same set of pinned sources: one document listing
    # several dates, or several documents that agree on the whole list (each value then
    # carries evidence from each of them). Different source sets are a real conflict.
    pin_sets, locations = set(), []
    shared_locator = False
    for candidate in candidates:
        current, pins = set(), set()
        for evidence in candidate.evidence:
            if not isinstance(evidence, VersionedEvidence):
                return False
            pins.add((evidence.document_id, evidence.source_version_id,
                      evidence.knowledge_revision_id))
            current.add((evidence.document_id, evidence.locator))
        pin_sets.add(frozenset(pins))
        shared_locator |= any(current & previous for previous in locations)
        locations.append(current)
    if len(pin_sets) != 1:
        return False
    words = set(field.split("_"))
    values = [c.value for c in candidates]
    if (words & {"date", "dates", "schedule"} and all(_date(v) for v in values)
            or words & {"time", "times", "hours", "schedule"} and all(_time(v) for v in values)):
        return len(set(values)) == len(values) and (not shared_locator or all(
            normalize_quote(e.quote) == normalize_quote(c.value)
            for c in candidates for e in c.evidence))
    if words & {"price", "prices", "fee", "amount"}:
        if shared_locator:
            return False
        # A bare pair of amounts is ambiguous. Only labelled variants, e.g.
        # "Adult: 20 EUR" / "Child: 10 EUR", establish different price dimensions.
        labels = [_price_variant(c) for c in candidates]
        return None not in labels and len(set(labels)) == len(labels)
    return False


def combine(candidates, *, inferred=False):
    """A derived list retains all citations and never grants inferred approval."""
    candidates = sorted(candidates, key=lambda c: c.id)
    values, seen, evidence = [], set(), []
    for candidate in candidates:
        items = candidate.value if isinstance(candidate.value, list) else [candidate.value]
        for value in items:
            key = json.dumps(value, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                values.append(value)
                seen.add(key)
        evidence.extend(candidate.evidence)
    states = {c.review_state for c in candidates}
    state = "accepted" if states == {"accepted"} else (
        "proposed" if inferred or "needs_review" not in states else "needs_review")
    return FactCandidate(id=candidates[0].id, lang=candidates[0].lang, value=values,
                         evidence=evidence, review_state=state)
