"""Lossless value/evidence views for the offline WP45 document-scoped scorer.

The scorer takes flat facts, not MergedField envelopes or versioned citations.
These views do not review facts, resolve conflicts, or read a golden key.
"""

from collections import defaultdict

from .match import source_identity
from .merge import _json
from .models import RECORD_MODELS


def _fact(candidate):
    return {"value": candidate.value, "lang": candidate.lang,
            "evidence": [{"document_id": e.document_id, "locator": e.locator, "quote": e.quote}
                         for e in candidate.evidence]}


def extraction_scoring_records(result):
    records = []
    for record in result.records:
        names = RECORD_MODELS[record.type][1].model_fields
        fields = {name: _fact(getattr(record, name)) for name in names
                  if getattr(record, name) is not None}
        conflicts = {}
        for name, alternatives in record.conflicts.items():
            languages = {c.lang for c in alternatives}
            candidates = [getattr(record, name),
                          *(getattr(f, name) for f in record.i18n.values()), *alternatives]
            distinct = []
            for candidate in candidates:
                if candidate is not None and candidate.lang in languages and _fact(candidate) not in distinct:
                    distinct.append(_fact(candidate))
            conflicts[name] = {"candidates": distinct, "review_state": "needs_review"}
        records.append({"id": record.id, "document_id": result.document_id, "type": record.type,
                        "fields": fields, "i18n": {
                            lang: {name: _fact(getattr(f, name)) for name in names
                                   if getattr(f, name) is not None}
                            for lang, f in record.i18n.items()}, "conflicts": conflicts})
    return records


def merged_scoring_views(revision, document_languages, *, source_language=False):
    """One view per contributing document; IDs retain the canonical ID as suffix.

    Default uses the actual EN-first display primary. A second, explicitly labeled
    source-language view compares available translations with monolingual goldens.
    Multiple candidates in the selected language have no display winner. All
    conflict alternatives stay visible, even when primary is absent.
    """
    records = []
    for record in revision.records:
        documents = {e.document_id for field in record.fields.values()
                     for candidate in field.candidates for e in candidate.evidence}
        for document_id in sorted(documents):
            fields, translations, conflicts = {}, defaultdict(dict), {}
            for name, field in record.fields.items():
                primary = field.primary
                if source_language:
                    choices = [c for c in field.candidates
                               if c.lang == document_languages[document_id] and c.review_state != "rejected"]
                    if choices:
                        accepted = [c for c in choices if c.review_state == "accepted"]
                        primary = accepted[0] if accepted else choices[0] if len(choices) == 1 else None
                if primary is not None:
                    fields[name] = _fact(primary)
                for lang, choices in field.i18n.items():
                    active = [c for c in choices if c.review_state != "rejected"]
                    if len(active) == 1:
                        translations[lang][name] = _fact(active[0])
                if field.conflicts:
                    conflicts[name] = {"candidates": [_fact(c) for choices in field.conflicts.values()
                                                     for c in choices],
                                       "review_state": field.review_state}
            records.append({"id": f"{document_id}:{record.id}", "document_id": document_id,
                            "canonical_record_id": record.id, "type": record.type,
                            "source_names": [_fact(c) for c in record.fields["name"].candidates
                                             if any(e.document_id == document_id for e in c.evidence)],
                            "fields": fields, "i18n": dict(translations), "conflicts": conflicts})
    return records


def merged_alignment_records(views, results, identity_map):
    """Use the contributing extraction's name for identity alignment only.

    An unresolved canonical name must remain absent for value scoring, but must
    not hide every other field by losing its known source identity. The proxy
    contains no expected values and never supplies facts to the value scorer.
    """
    source = defaultdict(list)
    for result in results:
        for record in result.records:
            source[result.document_id, record.type].append(record)
    proxies = []
    for view in views:
        matches = [r for r in source[view["document_id"], view["type"]]
                   if view["canonical_record_id"] in identity_map.get(
                       _json(["source", view["document_id"], r.type, source_identity(r)]), [])]
        if len(matches) != 1:
            raise ValueError("merged view does not have exactly one contributing source identity")
        record = matches[0]
        proxies.append({"id": view["id"], "document_id": view["document_id"], "type": view["type"],
                        "fields": {"name": _fact(record.name)},
                        "i18n": {lang: {"name": _fact(fields.name)}
                                 for lang, fields in record.i18n.items() if fields.name}})
    return proxies
