"""Source-grouped schedule questions and conservative two-record swap detection."""

from hashlib import sha256
from itertools import combinations

from .export import encode
from .schedule import display_dates, infer_schedule, parse_date, period_label


def schedule_question(question, groups, candidates, documents):
    shared = set.intersection(*(set(values) for values in groups.values()))
    difference = sorted(set.union(*(set(values) for values in groups.values())) - shared)
    options = []
    for document, dates in groups.items():
        selected = [c for c in candidates if any(
            getattr(e, "document_id", None) == document for e in c.evidence)]
        citations = [e.model_dump(mode="json") for c in selected for e in c.evidence
                     if getattr(e, "document_id", None) == document]
        changed = sorted(set(dates) - shared)
        schedule = infer_schedule(dates)
        short = display_dates(changed) if len(difference) <= 4 else (
            schedule["label_tr"] if schedule else display_dates([dates[0], dates[-1]]))
        if not changed:
            short = "Bu tarihlerde etkinlik yok"
        options.append({
            "candidate_id": min(c.id for c in selected), "value": changed,
            "display": short, "summary_tr": short, "quote": None, "locator": None,
            "document_id": document, "document_name": documents[document],
            "evidence": sorted(citations, key=lambda e: encode(e)),
            "program": [{"record_id": question["record_id"],
                         "record_title": question["record_title"], "dates": dates,
                         "schedule": schedule}],
        })
    label = period_label(parse_date(difference[0]), parse_date(difference[-1]))
    return {**question, "kind": "schedule_conflict", "options": options, "allow_all": False,
            "records": [question["record_title"]], "record_ids": [question["record_id"]],
            "period_label_tr": label, "differing_dates": difference,
            "question_tr": f"{question['record_title']} için {label} tarihlerinde hangi belge doğru?"}


def combine_swaps(questions, workspace, lineage):
    """Replace two slots only when both complete source programs cross-match in a period.

    Require at least three exchanged dates in each direction and exactly two sources.
    Other sources, isolated coincidences and partly matching programs remain questions.
    """
    slots = [q for q in questions if q["kind"] == "schedule_conflict" and len(q["options"]) == 2]
    consumed, swaps = set(), []
    for left, right in combinations(slots, 2):
        if left["id"] in consumed or right["id"] in consumed or left["record_id"] == right["record_id"]:
            continue
        if (left["collection"], left["field"], left["lang"]) != (
                right["collection"], right["field"], right["lang"]):
            continue
        a = {o["document_id"]: set(o["program"][0]["dates"]) for o in left["options"]}
        b = {o["document_id"]: set(o["program"][0]["dates"]) for o in right["options"]}
        if set(a) != set(b):
            continue
        first, second = sorted(a)
        if len(a[first] - a[second]) < 3 or len(a[second] - a[first]) < 3:
            continue
        if a[first] - a[second] != b[second] - b[first] or (
                a[second] - a[first] != b[first] - b[second]):
            continue
        changed = sorted(a[first] ^ a[second])
        start, end = changed[0], changed[-1]
        def during(values, start=start, end=end):
            return {d for d in values if start <= d <= end}
        if during(a[first]) != during(b[second]) or during(a[second]) != during(b[first]):
            continue
        # Both exchanged halves must themselves describe a recurring program.
        if any(infer_schedule(sorted(during(values))) is None for values in a.values()):
            continue
        suffix = end == max(set.union(*a.values(), *b.values()))
        label = period_label(parse_date(start), parse_date(end), suffix=suffix)
        if suffix and any(d < start and d[:7] == start[:7] for values in a.values() for d in values):
            label = display_dates([start]) + " itibaren"
        options = []
        for original in left["options"]:
            other = next(o for o in right["options"] if o["document_id"] == original["document_id"])
            program = original["program"] + other["program"]
            short = "; ".join(p["record_title"] + ": " + infer_schedule(
                sorted(during(set(p["dates"]))))["label_tr"] for p in program)
            options.append({**original, "value": [p["dates"] for p in program],
                            "program": program, "display": short, "summary_tr": short,
                            "evidence": original["evidence"] + other["evidence"]})
        names = [left["record_title"], right["record_title"]]
        weekdays = sorted({parse_date(d).weekday() for d in changed})
        when = "cumartesileri" if weekdays == [5] else "etkinlik tarihleri"
        identity = [workspace, lineage, "schedule_swap", left["record_id"], right["record_id"],
                    left["field"], left["lang"]]
        swaps.append({**left, "id": "q_" + sha256(encode(identity)).hexdigest(),
                      "kind": "schedule_swap", "records": names,
                      "record_ids": [left["record_id"], right["record_id"]],
                      "record_title": " ve ".join(names), "period_label_tr": label,
                      "question_tr": f"{label} {' ve '.join(names)}'nin {when} iki belgede "
                                     "yer değiştirmiş; hangi belge doğru?",
                      "options": options})
        consumed.update([left["id"], right["id"]])
    return [q for q in questions if q["id"] not in consumed] + swaps
