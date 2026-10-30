"""WP125: carry field decisions into an update, without changing the old revision.

Only current pinned contexts are searched. Source text is evidence data, never an
instruction. Historical citations remain on stale approvals until a person answers.

Per previous candidate (after merge, before decision 20):

- a person's decision (or a ``user_edit`` value) is kept exactly; its citations are
  re-pinned when the document is unchanged or the same quote is found in its new context;
- an approved value whose source changed (quote gone and a different value proposed) or was
  removed stays published and its slot becomes a question (``MergedField.source_changes``);
- a rule's approval whose source changed to a different value is dropped, so decision 20
  judges the replacement like any new value;
- a person's decision or correction that is kept, while a new or changed document gives another
  value in the same slot, also becomes a question (conflicts are asked, never resolved silently).
"""

from datetime import UTC, datetime

from .export import encode
from .merge_models import MergedField, UserEditEvidence, VersionedEvidence
from .runtime import revision_runtime
from .verify import normalize_quote


def unchanged(left, right):
    return (left is not None and right is not None and left.content_sha256 is not None
            and left.content_sha256 == right.content_sha256
            and left.knowledge_revision_id == right.knowledge_revision_id)


def _key(candidate):
    return encode([candidate.lang, candidate.value])


def _display(value):
    return value if isinstance(value, str) else encode(value).decode()


def _same_pin(citation, pin):
    return (citation.source_version_id, citation.knowledge_revision_id) == (
        pin.source_version_id, pin.knowledge_revision_id)


def _identities(record, runtime):
    field = record.fields.get(runtime.identities[record.type])
    return {_key(c) for c in field.candidates} if field else set()


def _anchors(record, runtime):
    field = record.fields.get(runtime.identities.get(record.type))
    return {(e.document_id, normalize_quote(e.quote)) for c in field.candidates
            for e in c.evidence if isinstance(e, VersionedEvidence)} if field else set()


def _align(revision, base):
    """Recover reviewed duplicate consolidations and stable IDs, conservatively.

    A fresh partition may belong to one reviewed record; ambiguous identity overlaps
    never grant a match. Source anchors take precedence over a shared display name.
    """
    runtime = revision_runtime(base)
    targets = {}
    for record in revision.records:
        possible = [old for old in base.records if old.type == record.type]
        exact = [old for old in possible if old.id == record.id]
        anchored = [old for old in possible
                    if _anchors(old, runtime) & _anchors(record, runtime)]
        named = [old for old in possible
                 if _identities(old, runtime) & _identities(record, runtime)]
        matches = exact or anchored or named
        target = matches[0].id if len(matches) == 1 else record.id
        record.id = target
        if target not in targets:
            targets[target] = record
            continue
        for key, incoming in record.fields.items():
            if key not in targets[target].fields:
                targets[target].fields[key] = incoming
            else:
                targets[target].fields[key].candidates.extend(incoming.candidates)
    revision.records = list(targets.values())


def carry_forward(revision, base, contexts):
    """Return an update and counts. Run before decision 20, so only new slots use it.

    ``contexts`` maps each current document_id to its pinned context (the extraction input).
    """
    revision = revision.model_copy(deep=True)
    counts = {"kept_decisions": 0, "reasked_decisions": 0, "new_values": 0, "removed_values": 0}
    if base is None:
        counts["new_values"] = sum(len(f.candidates) for r in revision.records for f in r.fields.values())
        return revision, counts
    _align(revision, base)
    runtime = revision_runtime(base)
    old_pins = {p.document_id: p for p in base.documents}
    pins = {p.document_id: p for p in revision.documents}
    rules = {(d.record_id, d.field, d.candidate_id) for d in base.decisions
             if d.reviewer.startswith("rule:")}
    answered = {(h.record_id, h.field, h.lang) for h in base.history}
    base_ids = {old.id for old in base.records}
    # What this run proposed, before any previous candidate is carried into it.
    fresh_fields = {(r.id, k): [c.model_copy(deep=True) for c in f.candidates]
                    for r in revision.records for k, f in r.fields.items()}
    counts["new_values"] += sum(len(f.candidates) for r in revision.records
                                if r.id not in base_ids for f in r.fields.values())
    carried, moved, visited = set(), {}, set()

    def current(candidate):
        """Citations that still hold in the pinned sources, and why the others do not."""
        evidence, lost = [], set()
        for citation in candidate.evidence:
            if isinstance(citation, UserEditEvidence):
                evidence.append(citation)
                continue
            pin = pins.get(citation.document_id)
            old = old_pins.get(citation.document_id)
            if pin is None and old is not None:
                lost.add("removed")
                continue
            if pin is None or (not _same_pin(citation, pin) and old is not None and unchanged(old, pin)
                               and not _same_pin(citation, old)):
                # Already historical on the head and nothing changed since: the answer stands.
                evidence.append(citation)
                continue
            if not (_same_pin(citation, pin) or (old is not None and unchanged(old, pin))):
                quote = normalize_quote(citation.quote)
                if not quote or quote not in normalize_quote(contexts.get(citation.document_id, "")):
                    lost.add("changed")
                    continue
            evidence.append(citation.model_copy(update={
                "source_version_id": pin.source_version_id,
                "knowledge_revision_id": pin.knowledge_revision_id}))
        return evidence, lost

    def refreshed(candidate):
        """Cites a document that is new or changed in this run (not as pinned on the head)."""
        return any(isinstance(e, VersionedEvidence) and e.document_id in pins
                   and not unchanged(old_pins.get(e.document_id), pins[e.document_id])
                   for e in candidate.evidence)

    def settled(field, lang):
        """Every document cited in this slot is exactly as it was on the head."""
        documents = {e.document_id for c in field.candidates if c.lang == lang
                     for e in c.evidence if isinstance(e, VersionedEvidence)}
        return all((key not in pins and key not in old_pins)
                   or unchanged(old_pins.get(key), pins.get(key)) for key in documents)

    records = {r.id: r for r in revision.records}
    for old in sorted(base.records, key=lambda r: r.id):
        target = records.get(old.id)
        if target is None:
            # A fresh run may join records that were separate; follow one unique source anchor.
            anchored = [r for r in records.values() if r.type == old.type and r.id not in base_ids
                        and _anchors(old, runtime) & _anchors(r, runtime)]
            if len(anchored) != 1:
                anchored = [r for r in records.values() if r.type == old.type
                            and _anchors(old, runtime) & _anchors(r, runtime)]
            target = anchored[0] if len(anchored) == 1 else None
            if target is not None:
                moved[old.id] = target.id
        if target is None:
            target = old.model_copy(deep=True)
            target.fields = {}
            records[old.id] = target
        for key, previous in old.fields.items():
            fresh = fresh_fields.get((target.id, key), [])
            old_keys = {_key(c) for c in previous.candidates}
            if (target.id, key) not in visited:
                visited.add((target.id, key))
                counts["new_values"] += sum(_key(c) not in old_keys for c in fresh)
            merged = target.fields.get(key)
            result = list(merged.candidates) if merged else []
            source_changes = dict(merged.source_changes) if merged else {}
            manual_langs = {c.lang for c in previous.candidates
                            if any(isinstance(e, UserEditEvidence) for e in c.evidence)}
            # An unanswered source question stays exactly as it was while its inputs are unchanged.
            pending = {lang: message for lang, message in previous.source_changes.items()
                       if settled(previous, lang)}
            held = {}
            for candidate in previous.candidates:
                decision_key = (old.id, key, candidate.id)
                if candidate.lang in pending:
                    result = [c for c in result if _key(c) != _key(candidate)]
                    result.append(candidate.model_copy(deep=True))
                    carried.add(decision_key)
                    continue
                human = (candidate.review_state in {"accepted", "rejected"}
                         and (decision_key not in rules or (old.id, key, candidate.lang) in answered))
                manual = candidate.lang in manual_langs
                evidence, lost = current(candidate)
                sourced = bool(evidence)
                accepted = candidate.review_state == "accepted"
                same = any(_key(c) == _key(candidate) for c in result)
                others = sorted({_display(c.value) for c in fresh if c.lang == candidate.lang
                                 and _key(c) != _key(candidate) and c.review_state != "rejected"})
                novel = any(c.lang == candidate.lang and _key(c) not in old_keys for c in fresh)
                stale = accepted and not manual and (not sourced or bool(lost and others))
                missing = not sourced and lost == {"removed"}
                if candidate.review_state != "rejected" and not sourced:
                    counts["removed_values"] += 1
                if manual or human:
                    keep = True
                elif stale:
                    # A rule's value that changed in its document is judged again by decision 20.
                    keep = missing or not others
                else:
                    keep = sourced and same and candidate.review_state != "proposed" and not novel
                if not keep:
                    continue
                saved = candidate.model_copy(deep=True)
                if not stale and sourced:
                    saved.evidence = evidence
                result = [c for c in result if _key(c) != _key(candidate)]
                result.append(saved)
                carried.add(decision_key)
                if not stale and (human or manual):
                    counts["kept_decisions"] += 1
                    if accepted:
                        held.setdefault(candidate.lang, saved)
                if stale:
                    counts["reasked_decisions"] += int(candidate.lang not in source_changes)
                    value = _display(candidate.value)
                    if missing:
                        message = f"Güncel kaynak yok: önceki onaylı değer {value}"
                    elif others:
                        message = (f"Belge değişti: önceki onaylı değer {value}, "
                                   f"belgedeki yeni değer {', '.join(others)}")
                    else:
                        message = f"Belge değişti: önceki onaylı değer {value} belgede artık bulunamadı"
                    source_changes[candidate.lang] = message
            # Conflicts are asked, never resolved silently: a new or changed document that gives
            # another value for a person's decision reopens the slot (unchanged documents do not).
            for lang, kept in sorted(held.items()):
                incoming = [c for c in fresh if c.lang == lang and c.review_state != "rejected"
                            and _key(c) not in old_keys and _key(c) != _key(kept) and refreshed(c)]
                if lang in source_changes or lang in pending or not incoming:
                    continue
                documents = {e.document_id for c in incoming for e in c.evidence
                             if isinstance(e, VersionedEvidence)}
                cited = {e.document_id for e in kept.evidence if isinstance(e, VersionedEvidence)}
                value = _display(kept.value)
                values = ", ".join(sorted({_display(c.value) for c in incoming}))
                if documents - old_pins.keys():
                    message = f"Yeni belge farklı bir değer veriyor: onaylı değer {value}, belgedeki değer {values}"
                elif documents & cited:
                    message = f"Belge değişti: önceki onaylı değer {value}, belgedeki yeni değer {values}"
                else:
                    message = (f"Değişen belge farklı bir değer veriyor: onaylı değer {value}, "
                               f"belgedeki değer {values}")
                source_changes[lang] = message
                counts["reasked_decisions"] += 1
            source_changes.update(pending)
            # The previous value stays published; new values in its slot wait for the answer.
            for c in result:
                if c.lang in source_changes and c.review_state == "proposed":
                    c.review_state = "needs_review"
            for lang in manual_langs - source_changes.keys():
                # Values from unchanged documents stay behind the person's correction.
                old_ids = {c.id for c in previous.candidates if c.lang == lang}
                for c in result:
                    if c.lang == lang and c.id not in old_ids:
                        c.review_state = "rejected"
            if not result:
                target.fields.pop(key, None)
                continue
            languages = {c.lang for c in result}
            target.fields[key] = MergedField(
                primary_lang=(previous.primary_lang if previous.primary_lang in languages
                              else merged.primary_lang if merged and merged.primary_lang in languages
                              else min(languages)),
                candidates=result,
                multi_value_languages=sorted(set(previous.multi_value_languages)
                                             | set(merged.multi_value_languages if merged else [])),
                source_changes=source_changes)
    # Rule values that a fresh consolidation placed in another record leave an empty shell.
    revision.records = [r for r in records.values() if r.fields]
    historical = {(p.document_id, p.source_version_id, p.knowledge_revision_id): p
                  for p in base.documents + base.historical_documents}
    current_pins = {(p.document_id, p.source_version_id, p.knowledge_revision_id)
                    for p in revision.documents}
    referenced = {(e.document_id, e.source_version_id, e.knowledge_revision_id)
                  for r in revision.records for f in r.fields.values()
                  for c in f.candidates for e in c.evidence if isinstance(e, VersionedEvidence)}
    revision.historical_documents = [historical[key].model_copy(deep=True)
                                     for key in sorted(referenced - current_pins) if key in historical]
    revision.decisions = [d.model_copy(deep=True, update={"record_id": moved.get(d.record_id, d.record_id)})
                          for d in base.decisions if (d.record_id, d.field, d.candidate_id) in carried]
    revision.history = [h.model_copy(deep=True, update={"record_id": moved.get(h.record_id, h.record_id)})
                        for h in base.history]
    revision.duplicate_decisions = [d.model_copy(deep=True) for d in base.duplicate_decisions]
    revision.user_changes = [c.model_copy(deep=True) for c in base.user_changes]
    revision.parent_id = base.id
    revision.lineage_id = base.lineage_id or base.id
    revision.updated_at = datetime.now(UTC).isoformat()
    return revision, counts
