"""Offline, conservative record reconciliation and immutable field history."""

import json
import os
import tempfile
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from docgrain_eval.scoring import normalized_value

from .merge_models import (
    AliasDecision,
    FactCandidate,
    FieldChange,
    MatchIssue,
    MergedField,
    MergeDocument,
    MergedRecord,
    MergeRevision,
    MergeState,
    ReviewDecision,
    RevisionDiff,
    SourcePin,
    VersionedEvidence,
)
from .models import Text
from .runtime import HOSPITALITY
from .verify import _blocks, normalize_quote
from .verify import _source_key as evidence_source_key


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _payload(model):
    return model.model_dump(mode="json", round_trip=True)


def _id(prefix: str, value) -> str:
    return prefix + uuid5(NAMESPACE_URL, _json(value)).hex


def _source_key(document, item) -> str:
    return _json(["source", document.document_id, item.record.type, item.source_identity])


def _keys(document, item):
    source = _source_key(document, item)
    aliases = {_json(["alias", item.record.type, alias]) for alias in item.aliases}
    names = [item.record.name]
    names.extend(fields.name for fields in item.record.i18n.values() if fields.name)
    normalized = {_json(["name", item.record.type, name.lang,
                         normalize_quote(name.value).casefold()]) for name in names}
    return source, aliases, normalized


def _facts(document, item, runtime):
    blocks = _blocks(document.context)
    source = normalize_quote(document.context)
    _, fields_model = runtime.models[item.record.type]
    for field in fields_model.model_fields:
        alternatives = [getattr(item.record, field)]
        alternatives.extend(getattr(fields, field) for fields in item.record.i18n.values())
        alternatives.extend(item.record.conflicts.get(field, []))
        for fact in alternatives:
            if fact is None:
                continue
            if runtime.schema:
                runtime.validate_value(item.record.type, field, fact.value)
            evidence = []
            for citation in fact.evidence:
                quote = normalize_quote(citation.quote)
                locator = evidence_source_key(citation.locator)
                if (citation.document_id != document.document_id
                    or (blocks and locator not in blocks)
                    or not quote or quote not in blocks.get(locator, source)):
                    raise ValueError("merge requires verified evidence in the pinned source context")
                evidence.append(VersionedEvidence(
                    **_payload(citation), source_version_id=document.source_version_id,
                    knowledge_revision_id=document.knowledge_revision_id,
                ))
            yield field, fact.lang, fact.value, evidence


def _match(workspace_id, entries, identity_map):
    """Strong identities first; ambiguous weak connected components never collapse."""
    parents = list(range(len(entries)))
    anchors = [set() for _ in entries]
    strong, weak = defaultdict(list), defaultdict(list)
    keys = []
    for index, (document, item) in enumerate(entries):
        source, aliases, names = _keys(document, item)
        keys.append((source, aliases, names))
        for key in {source} | aliases:
            strong[key].append(index)
            anchors[index].update(identity_map.get(key, []))
        for key in names:
            weak[key].append(index)

    def root(index):
        while parents[index] != index:
            index = parents[index]
        return index

    def union(left, right):
        left, right = root(left), root(right)
        if left != right:
            parents[max(left, right)] = min(left, right)

    # Known IDs themselves connect translated/renamed inputs after a restart.
    known = defaultdict(list)
    for index, ids in enumerate(anchors):
        if len(ids) > 1:
            raise ValueError("explicit identity links multiple existing records")
        for record_id in ids:
            known[record_id].append(index)
    for indices in strong.values():
        for index in indices[1:]:
            union(indices[0], index)
    for record_id, indices in known.items():
        excluded = any(keys[b][0] in entries[a][1].match_exclusions
                       for a in indices for b in indices)
        if not excluded:
            for index in indices[1:]:
                union(indices[0], index)
            continue
        # A withdrawn reviewed match must not survive through historical ID
        # anchors. Keep the ID on the first source partition; detached sources
        # get stable new IDs. Prior revisions and their review trail are intact.
        partitions = defaultdict(list)
        for index in indices:
            partitions[root(index)].append(index)
        ordered = sorted(partitions.values(), key=lambda group: min(keys[i][0] for i in group))
        for partition in ordered[1:]:
            detached_id = _id("rec_", [workspace_id, "split", record_id,
                                       min(keys[i][0] for i in partition)])
            for index in partition:
                anchors[index] = {detached_id}
                source, aliases, _ = keys[index]
                for key in {source} | aliases:
                    identity_map[key] = [detached_id]

    groups = defaultdict(list)
    for index in range(len(entries)):
        groups[root(index)].append(index)
    for indices in groups.values():
        if len(set().union(*(anchors[index] for index in indices))) > 1:
            raise ValueError("explicit identity links multiple existing records")

    # Evaluate whole weak components before joining any edge. This avoids an
    # order-dependent bridge between two existing IDs through a new candidate.
    strong_roots = {index: root(index) for index in range(len(entries))}
    for indices in weak.values():
        for index in indices[1:]:
            union(indices[0], index)
    weak_groups = defaultdict(list)
    for index in range(len(entries)):
        weak_groups[root(index)].append(index)
    issues = []
    resolved = {}
    for indices in weak_groups.values():
        ids = set().union(*(anchors[index] for index in indices))
        names = set().union(*(keys[index][2] for index in indices))
        for name in names:
            ids.update(identity_map.get(name, []))
        per_document = defaultdict(set)
        for index in indices:
            per_document[entries[index][0].document_id].add(strong_roots[index])
        ambiguous = len(ids) > 1 or any(len(roots) > 1 for roots in per_document.values())
        excluded = any(keys[b][0] in entries[a][1].match_exclusions
                       and strong_roots[a] != strong_roots[b] for a in indices for b in indices)
        ambiguous = ambiguous or excluded
        if ambiguous:
            separate = defaultdict(list)
            for index in indices:
                separate[strong_roots[index]].append(index)
            for name in sorted(names):
                issues.append(MatchIssue(key=name, source_keys=sorted(
                    keys[index][0] for index in indices if name in keys[index][2]),
                    reason="excluded_pair" if excluded else "ambiguous_normalized_key"))
            partitions = list(separate.values())
        else:
            partitions = [indices]
        for partition in partitions:
            existing = set().union(*(anchors[index] for index in partition))
            if not ambiguous:
                existing.update(ids)
            record_id = next(iter(existing)) if existing else _id(
                "rec_", [workspace_id, min(keys[index][0] for index in partition)])
            for index in partition:
                resolved[index] = record_id
    for index, record_id in resolved.items():
        source, aliases, names = keys[index]
        for key in {source} | aliases | names:
            identity_map[key] = sorted(set(identity_map.get(key, [])) | {record_id})
    return resolved, sorted(issues, key=lambda issue: issue.key)


def _merge(state, revision_id, documents, decisions, alias_decisions, runtime):
    entries = [(document, item) for document in documents for item in document.records]
    # Verify before identity allocation, even if a model was bypassed or mutated.
    facts = [list(_facts(document, item, runtime)) for document, item in entries]
    # Only reviewed alias decisions may consolidate established IDs. Historical
    # revisions remain immutable; update just the mapping used by this revision.
    known_types = {record.id: record.type for revision in state.revisions.values()
                   for record in revision.records}
    retired = set()
    keepers = {decision.keep_id for decision in alias_decisions}
    for decision in alias_decisions:
        if (decision.keep_id == decision.retired_id or decision.retired_id in retired
            or decision.retired_id in keepers or decision.keep_id not in known_types
            or known_types.get(decision.retired_id) != known_types[decision.keep_id]):
            raise ValueError("alias decision must consolidate distinct existing IDs of one type")
        retired.add(decision.retired_id)
        for key, ids in state.identity_map.items():
            state.identity_map[key] = sorted({decision.keep_id if record_id == decision.retired_id
                                              else record_id for record_id in ids})
    resolved, issues = _match(state.workspace_id, entries, state.identity_map)
    grouped, types = defaultdict(lambda: defaultdict(dict)), {}
    for index, (_, item) in enumerate(entries):
        record_id = resolved[index]
        types[record_id] = item.record.type
        for field, lang, value, evidence in facts[index]:
            key = _json([lang, normalized_value(value, field)])
            bucket = grouped[record_id][field].setdefault(key, [lang, value, {}])
            for citation in evidence:
                bucket[2][_json(_payload(citation))] = citation
    records = []
    for record_id in sorted(grouped):
        fields = {}
        for field, alternatives in sorted(grouped[record_id].items()):
            candidates = []
            for key, (lang, value, citations) in sorted(alternatives.items()):
                evidence = [citations[key] for key in sorted(citations)]
                candidates.append(FactCandidate(
                    id=_id("fact_", [record_id, field, key, [_payload(e) for e in evidence]]),
                    value=value, lang=lang, evidence=evidence,
                    review_state="needs_review" if sum(
                        entry[0] == lang for entry in alternatives.values()) > 1 else "proposed",
                ))
            languages = {c.lang for c in candidates}
            primary_lang = min(languages, key=lambda lang: (
                0 if lang == "en" else 1 if lang.split("-")[0] == "en" else 2, lang))
            fields[field] = MergedField(primary_lang=primary_lang, candidates=candidates)
        records.append(MergedRecord(id=record_id, type=types[record_id], fields=fields))
    index = {(record.id, field, candidate.id): candidate
             for record in records for field, merged in record.fields.items()
             for candidate in merged.candidates}
    seen = set()
    for decision in decisions:
        key = (decision.record_id, decision.field, decision.candidate_id)
        if key not in index or key in seen:
            raise ValueError("review decision must target one current candidate exactly once")
        seen.add(key)
        index[key].review_state = decision.action
    for record in records:
        for field in record.fields.values():
            for lang in {c.lang for c in field.candidates}:
                if sum(c.lang == lang and c.review_state == "accepted" for c in field.candidates) > 1:
                    raise ValueError("only one candidate per language may be accepted")
    return MergeRevision(
        workspace_id=state.workspace_id, id=revision_id,
        documents=[SourcePin(document_id=d.document_id, source_version_id=d.source_version_id,
                             knowledge_revision_id=d.knowledge_revision_id,
                             content_sha256=d.content_sha256,
                             document_name=d.document_name) for d in documents],
        records=records, match_issues=issues,
        decisions=sorted(decisions, key=lambda d: (d.record_id, d.field, d.candidate_id)),
        alias_decisions=alias_decisions,
        workspace_schema=runtime.schema,
    )


class JsonMergeStore:
    """Local workspace store; atomic single-writer commits include identity and history.

    A merge receives the complete active document set. Omission means deletion,
    never an incremental re-ingestion. An existing revision ID is immutable.
    """

    def __init__(self, path: str | Path, workspace_id: str):
        from pydantic import TypeAdapter

        self.path = Path(path)
        self.workspace_id = TypeAdapter(Text).validate_python(workspace_id)
        self._read()

    def _read(self):
        state = (MergeState.model_validate_json(self.path.read_text(encoding="utf-8"))
                 if self.path.exists() else MergeState(workspace_id=self.workspace_id))
        if state.workspace_id != self.workspace_id or any(
            revision.workspace_id != self.workspace_id for revision in state.revisions.values()
        ):
            raise ValueError("merge store belongs to another workspace")
        return state

    def get_revision(self, revision_id: str) -> MergeRevision:
        # Read/parse afresh: caller mutation cannot affect stored history.
        return self._read().revisions[revision_id]

    def merge(self, revision_id: str, documents: list[MergeDocument],
              decisions: list[ReviewDecision] | None = None,
              alias_decisions: list[AliasDecision] | None = None, *, runtime=None) -> MergeRevision:
        from pydantic import TypeAdapter

        TypeAdapter(Text).validate_python(revision_id)
        runtime = runtime or HOSPITALITY
        if runtime.schema and runtime.schema["workspace_id"] != self.workspace_id:
            raise ValueError("collection schema belongs to another workspace")
        documents = [runtime.merge_document(_payload(d)) for d in documents]
        decisions = [ReviewDecision.model_validate(_payload(d)) for d in (decisions or [])]
        alias_decisions = sorted([AliasDecision.model_validate(_payload(d))
                                  for d in (alias_decisions or [])],
                                 key=lambda d: (d.keep_id, d.retired_id))
        if any(d.workspace_id != self.workspace_id for d in documents):
            raise ValueError("cannot merge documents from another workspace")
        unique = {}
        for document in documents:
            document.records.sort(key=lambda item: (item.record.type, item.source_identity))
            for item in document.records:
                item.aliases = sorted(set(item.aliases))
            if document.document_id in unique and document != unique[document.document_id]:
                raise ValueError("one pinned version per document is required")
            unique[document.document_id] = document
        documents = [unique[key] for key in sorted(unique)]
        decisions.sort(key=lambda d: (d.record_id, d.field, d.candidate_id))
        request = [[_payload(d) for d in documents], [_payload(d) for d in decisions]]
        # Empty matcher vetoes preserve wp42 request digests for saved revisions.
        for document in request[0]:
            if document["document_name"] is None:
                document.pop("document_name")
            if document["content_sha256"] is None:
                document.pop("content_sha256")
            for item in document["records"]:
                if not item["match_exclusions"]:
                    item.pop("match_exclusions")
        if alias_decisions:
            request.append([_payload(d) for d in alias_decisions])
        if runtime.schema:
            request.append(runtime.schema)
        digest = sha256(_json(request).encode("utf-8")).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_name(self.path.name + ".lock")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ValueError("merge store already has a writer") from exc
        os.close(descriptor)
        temporary = None
        try:
            state = self._read()
            previous = state.revisions.get(revision_id)
            if previous is not None:
                if state.request_digests.get(revision_id) != digest:
                    raise ValueError("existing merge revision is immutable")
                return previous
            revision = _merge(state, revision_id, documents, decisions, alias_decisions, runtime)
            state.revisions[revision_id] = revision
            state.request_digests[revision_id] = digest
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             delete=False) as output:
                temporary = Path(output.name)
                output.write(state.model_dump_json(indent=2, round_trip=True))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            return revision
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
            lock.unlink()


def _signatures(field):
    if field is None:
        return (None, []), [], [], [], []
    primary = sorted(_json([c.lang, c.value]) for c in field.candidates
                     if c.lang.split("-")[0] == "en" or c.lang == field.primary_lang)
    translations = sorted(_json([c.lang, c.value]) for c in field.candidates
                          if c.lang.split("-")[0] != "en")
    # Include all languages (also English regions) and associate citations with facts.
    evidence = sorted(_json([c.lang, c.value, [_payload(e) for e in c.evidence]])
                      for c in field.candidates)
    conflicts = sorted(_json([lang, [c.value for c in choices]])
                       for lang, choices in field.conflicts.items())
    review = sorted(_json([c.lang, c.review_state,
                           c.value if c.review_state in {"accepted", "rejected"} else None])
                    for c in field.candidates)
    return (field.primary_lang, primary), translations, evidence, conflicts, review


def compare_revisions(before: MergeRevision, after: MergeRevision) -> RevisionDiff:
    """Field changes include independent fact, translation, evidence and review flags."""
    if before.workspace_id != after.workspace_id:
        raise ValueError("cannot compare different workspaces")
    old, new = ({r.id: r for r in revision.records} for revision in (before, after))
    changes = []
    for record_id in sorted(old.keys() | new.keys()):
        old_fields = old[record_id].fields if record_id in old else {}
        new_fields = new[record_id].fields if record_id in new else {}
        for name in sorted(old_fields.keys() | new_fields.keys()):
            left, right = old_fields.get(name), new_fields.get(name)
            flags = [a != b for a, b in zip(_signatures(left), _signatures(right))]
            if left is not None and right is not None and not any(flags):
                continue
            changes.append(FieldChange(
                record_id=record_id, field=name,
                kind="added" if left is None else "removed" if right is None else "changed",
                value_changed=flags[0], i18n_changed=flags[1], evidence_changed=flags[2],
                conflicts_changed=flags[3], review_changed=flags[4],
                before=left.model_copy(deep=True) if left else None,
                after=right.model_copy(deep=True) if right else None,
            ))
    return RevisionDiff(workspace_id=before.workspace_id, before_id=before.id, after_id=after.id,
                        added_records=sorted(new.keys() - old.keys()),
                        removed_records=sorted(old.keys() - new.keys()), fields=changes)
