"""Decision 20 (WP111): accept verified, non-conflicting field values by a recorded rule.

Per record, field and language slot, after the merge:

- every candidate must still be verified (pinned source, quotation states the value);
- candidates whose values are equal after formatting normalization, or near-identical long
  text, are one value: the best-sourced candidate is accepted and each other spelling stays in
  the revision as a rejected *variant* with its own rule decision and evidence;
- one document listing several values that the cardinality rules already treat as a list
  (distinct dates/times, labelled prices, list fields) is accepted as that list;
- anything else (different numbers, times or dates, unverified evidence, user edits) stays
  ``needs_review`` and becomes a question exactly as before.

Each automatic state is a ``ReviewDecision`` whose reviewer names the rule, so it is auditable
and a person can still change it (``review.auto_accepted`` + the answer API).
"""

from .merge_models import MergeRevision, ReviewDecision, VersionedEvidence
from .multivalue import multiple_values
from .normalize import format_key, mentions, near_identical
from .runtime import revision_runtime

RULES_VERSION = "wp111"
RULE_SINGLE = "rule:verified-single-source"
RULE_AGREEING = "rule:verified-agreeing-sources"
RULE_FORMAT = "rule:format-equal-variant"
RULE_NEAR = "rule:near-identical-variant"
# Existing U1 reviewer for values that need a person (unchanged wording).
RULE_HUMAN = "rule:u1-human-field-review"
HUMAN_REASON = "Kimlik eşleşmesi alan onayı değildir; insan onayı gerekli."
REASONS = {
    RULE_SINGLE: "Tek kaynak; alıntı kaynakta doğrulandı ve çelişen değer yok (karar 20).",
    RULE_AGREEING: "Kaynaklar aynı değeri veriyor (yalnız yazım farkı olabilir); "
                   "alıntılar doğrulandı (karar 20).",
    "multi": "Tek belge bu alan için birden çok değer listeliyor; alıntılar doğrulandı (karar 20).",
}


def _documents(candidate):
    return {e.document_id for e in candidate.evidence if isinstance(e, VersionedEvidence)}


def _verified(candidate, pins, field):
    """Evidence passed verify.py at extraction; recheck pins and that each quote states the value."""
    return bool(candidate.evidence) and all(
        isinstance(e, VersionedEvidence)
        and (e.document_id, e.source_version_id, e.knowledge_revision_id) in pins
        and mentions(e.quote, candidate.value, field)
        for e in candidate.evidence)


def _groups(field, candidates):
    """Formatting-equal buckets, then complete-linkage joins of near-identical long text."""
    buckets = {}
    for candidate in sorted(candidates, key=lambda c: c.id):
        buckets.setdefault(format_key(candidate.value, field), []).append(candidate)
    groups = list(buckets.values())
    joined = True
    while joined:
        joined = False
        for i, left in enumerate(groups):
            for j in range(i + 1, len(groups)):
                if all(near_identical(a.value, b.value) for a in left for b in groups[j]):
                    groups[i] = left + groups.pop(j)
                    joined = True
                    break
            if joined:
                break
    return groups


def _best(candidates):
    return min(candidates, key=lambda c: (-len(_documents(c)), -len(c.evidence), c.id))


def plan_slot(runtime, record, field, merged, lang, pins):
    """Return [(candidate, state, reviewer, reason)] for an automatic outcome, else None."""
    slot = [c for c in merged.candidates if c.lang == lang]
    if any(c.review_state not in {"proposed", "needs_review"} for c in slot):
        return None  # A decision already exists for this slot.
    if not all(_verified(c, pins, field) for c in slot):
        return None
    groups = _groups(field, slot)
    if len(groups) == 1:
        members = groups[0]
        kept = _best(members)
        documents = set().union(*(_documents(c) for c in members))
        rule = RULE_SINGLE if len(members) == 1 and len(documents) == 1 else RULE_AGREEING
        plan = [(kept, "accepted", rule, REASONS[rule])]
        for other in members:
            if other is kept:
                continue
            same = format_key(other.value, field) == format_key(kept.value, field)
            plan.append((other, "rejected", RULE_FORMAT if same else RULE_NEAR,
                         (f"Yalnız yazımı farklı; {kept.id} ile aynı değer, varyant olarak saklandı."
                          if same else
                          f"Neredeyse aynı uzun metin (yazım/OCR farkı); {kept.id} tutuldu, "
                          "bu yazım varyant olarak saklandı.")))
        return plan
    documents = set().union(*(_documents(c) for c in slot))
    if len(documents) == 1 and multiple_values(runtime, record, field, merged, lang, slot):
        return [(c, "accepted", RULE_SINGLE, REASONS["multi"]) for c in slot]
    return None


def apply_review_rules(revision: MergeRevision) -> tuple[MergeRevision, list[dict]]:
    """Automatic acceptance for agreeing verified values; every other proposal needs a person."""
    revision = revision.model_copy(deep=True)
    runtime = revision_runtime(revision)
    pins = {(p.document_id, p.source_version_id, p.knowledge_revision_id) for p in revision.documents}
    decisions, audit = [], []

    def mark(record, field, candidate, state, reviewer, reason):
        if candidate.review_state == state:
            return
        candidate.review_state = state
        audit.append({"record_id": record.id, "field": field, "candidate_id": candidate.id,
                      "state": state, "reviewer": reviewer, "reason": reason})
        if state != "needs_review":
            decisions.append(ReviewDecision(record_id=record.id, field=field,
                                            candidate_id=candidate.id, action=state,
                                            reviewer=reviewer, reason=reason))

    for record in sorted(revision.records, key=lambda r: r.id):
        for field, merged in sorted(record.fields.items()):
            for lang in sorted({c.lang for c in merged.candidates}):
                plan = plan_slot(runtime, record, field, merged, lang, pins)
                for candidate, state, reviewer, reason in plan or []:
                    mark(record, field, candidate, state, reviewer, reason)
                for candidate in merged.candidates:
                    if candidate.lang == lang and candidate.review_state == "proposed":
                        mark(record, field, candidate, "needs_review", RULE_HUMAN, HUMAN_REASON)
    revision.decisions = sorted(revision.decisions + decisions,
                                key=lambda d: (d.record_id, d.field, d.candidate_id))
    return MergeRevision.model_validate_json(revision.model_dump_json(round_trip=True)), audit


def rule_decisions(revision: MergeRevision) -> dict:
    """(record, field, candidate) -> automatic decision; people never use the rule: prefix."""
    return {(d.record_id, d.field, d.candidate_id): d for d in revision.decisions
            if d.reviewer.startswith("rule:")}


def auto_slots(revision: MergeRevision) -> list[tuple]:
    """Slots settled only by a rule (no answer yet): (record, field, lang, candidates)."""
    rules = rule_decisions(revision)
    answered = {(h.record_id, h.field, h.lang) for h in revision.history}
    result = []
    for record in sorted(revision.records, key=lambda r: r.id):
        for field, merged in sorted(record.fields.items()):
            for lang in sorted({c.lang for c in merged.candidates}):
                slot = [c for c in merged.candidates if c.lang == lang]
                accepted = [c for c in slot if c.review_state == "accepted"]
                if (not accepted or (record.id, field, lang) in answered
                        or any((record.id, field, c.id) not in rules for c in accepted)):
                    continue
                result.append((record, field, lang, [
                    c for c in slot if c.review_state == "accepted"
                    or (record.id, field, c.id) in rules]))
    return result


def human_accepted(revision: MergeRevision) -> bool:
    """An acceptance a person made (an answer), as opposed to a recorded rule."""
    rules = {key for key, d in rule_decisions(revision).items() if d.action == "accepted"}
    answered = {(h.record_id, h.field, h.lang) for h in revision.history}
    return any(c.review_state == "accepted" and ((record.id, field, c.id) not in rules
                                                 or (record.id, field, c.lang) in answered)
               for record in revision.records for field, merged in record.fields.items()
               for c in merged.candidates)
