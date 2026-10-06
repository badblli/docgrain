"""Deterministic date summaries. Dates and their citations remain the source of truth."""

import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from itertools import combinations

from .merge_models import VersionedEvidence

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
WEEKDAYS_TR = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
MONTHS_TR = ("Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara")
MONTHS_FROM_TR = ("Ocak'tan", "Şubat'tan", "Mart'tan", "Nisan'dan", "Mayıs'tan", "Haziran'dan",
                  "Temmuz'dan", "Ağustos'tan", "Eylül'den", "Ekim'den", "Kasım'dan", "Aralık'tan")


def date_field(field):
    return bool(set(field.split("_")) & {"date", "dates", "schedule"})


def parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value)
        match = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", value.strip())
        if match:
            day, month, year = map(int, match.groups())
            return date(year, month, day)
    except ValueError:
        pass
    return None


def date_values(values):
    """Normalize a complete list, never silently discard an invalid date."""
    parsed = [parse_date(value) for value in values]
    return sorted(set(parsed)) if parsed and all(parsed) else None


def display_dates(values):
    dates = date_values(values)
    return ", ".join(f"{d.day} {MONTHS_TR[d.month - 1]} {d.year}" for d in dates) if dates else "—"


def period_label(start, end, *, suffix=False):
    if suffix:
        return MONTHS_FROM_TR[start.month - 1] + " itibaren"
    if start == end:
        return display_dates([start.isoformat()])
    return display_dates([start.isoformat()]) + " – " + display_dates([end.isoformat()])


def infer_schedule(values):
    """Fit weekly/fortnightly phases with at least three dates and limited exceptions.

    Minimize missing + extra dates, then the number of phases. Each phase must recur
    at least twice; at least two thirds of the observed dates must fit the rule.
    No dates outside the observed range are invented in the published date list.
    """
    dates = date_values(values)
    if not dates or len(dates) < 3:
        return None
    observed = set(dates)
    fits = []
    for interval in (7, 14):
        counts = Counter(d.toordinal() % interval for d in dates)
        phases = sorted(p for p, count in counts.items() if count >= 2)
        for size in range(1, len(phases) + 1):
            for residues in combinations(phases, size):
                expected = {dates[0] + timedelta(days=offset)
                            for offset in range((dates[-1] - dates[0]).days + 1)
                            if (dates[0].toordinal() + offset) % interval in residues}
                missing, extra = expected - observed, observed - expected
                errors = len(missing) + len(extra)
                if len(observed & expected) >= 3 and errors <= len(dates) // 3:
                    fits.append((errors, size, interval, residues, missing, extra))
    if not fits:
        return None
    _, _, interval, residues, missing, extra = min(fits, key=lambda item: item[:4])
    weekdays = sorted({d.weekday() for d in dates if d.toordinal() % interval in residues})
    weekday_names = [WEEKDAYS[d] for d in weekdays]
    label = ("Her hafta " if interval == 7 else "2 haftada bir ") + ", ".join(
        WEEKDAYS_TR[d] for d in weekdays)
    start, end = dates[0], dates[-1]
    first = f"{start.day} {MONTHS_TR[start.month - 1]}" + (
        f" {start.year}" if start.year != end.year else "")
    label += f", {first} – {end.day} {MONTHS_TR[end.month - 1]} {end.year}"
    if missing:
        label += "; eksik: " + display_dates([d.isoformat() for d in sorted(missing)])
    if extra:
        label += "; ek: " + display_dates([d.isoformat() for d in sorted(extra)])
    return {"weekday": weekday_names[0] if len(weekday_names) == 1 else weekday_names,
            "every_days": interval, "from": start.isoformat(), "to": end.isoformat(),
            "missing": [d.isoformat() for d in sorted(missing)],
            "extra": [d.isoformat() for d in sorted(extra)], "label_tr": label}


def document_dates(field, candidates):
    """Only date slots with >=3 dates per document qualify for schedule reasoning.

    User edits and multiple versions of one document require ordinary review.
    Scalar dates and declared date lists use the same comparison rules.
    """
    if not date_field(field):
        return None
    groups, pins = defaultdict(set), defaultdict(set)
    for candidate in candidates:
        dates = date_values(candidate.value if isinstance(candidate.value, list)
                            else [candidate.value])
        if not dates:
            return None
        for evidence in candidate.evidence:
            if not isinstance(evidence, VersionedEvidence):
                return None
            groups[evidence.document_id].update(d.isoformat() for d in dates)
            pins[evidence.document_id].add((evidence.source_version_id,
                                           evidence.knowledge_revision_id))
    if not groups or any(len(values) < 3 for values in groups.values()) or any(
            len(versions) != 1 for versions in pins.values()):
        return None
    return {key: sorted(values) for key, values in sorted(groups.items())}


def same_recurrence(groups):
    """Agree on the phase and every date in overlapping coverage; allow partial ranges."""
    if len({tuple(values) for values in groups.values()}) == 1:
        return True
    schedules = [infer_schedule(values) for values in groups.values()]
    if not schedules or any(s is None or s["extra"] for s in schedules):
        return False
    phases = {(s["every_days"], tuple(sorted({parse_date(value).toordinal() % s["every_days"]
                                           for value in values})))
              for s, values in zip(schedules, groups.values(), strict=True)}
    if len(phases) != 1:
        return False
    for left, right in combinations(groups.values(), 2):
        start, end = max(left[0], right[0]), min(left[-1], right[-1])
        if {d for d in left if start <= d <= end} != {d for d in right if start <= d <= end}:
            return False
    return True
