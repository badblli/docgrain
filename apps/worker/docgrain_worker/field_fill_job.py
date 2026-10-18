"""WP120: fill one field outside the workspace lock; publish one fenced child."""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from docgrain_api import records_jobs as lifecycle
from docgrain_api.field_fill import fill_from_contexts, load_pinned_contexts

from .records_pipeline import Pipeline, PipelineError


class FieldFillJob(Pipeline):
    stages = lifecycle.FILL_STAGES
    labels = lifecycle.FILL_LABELS
    stage_timeouts = lifecycle.FILL_STAGE_TIMEOUTS

    def fill(self):
        resolved = self.guard()
        base = self.store._source(self.workspace, self.job["base_revision_id"])
        documents = load_pinned_contexts(self.store, base, self.job["context_job_id"])
        child = base.model_copy(deep=True)
        child.id = "rev_" + uuid4().hex
        child.parent_id = base.id
        child.lineage_id = base.lineage_id or base.id
        child.updated_at = datetime.now(UTC).isoformat()
        self.revision, note, rejected = fill_from_contexts(
            child, self.job["collection"], self.job["field"], documents,
            resolved, self.guard, self.transport, on_usage=self.account("fill"))
        change = next(change for change in reversed(self.revision.user_changes)
                      if change.kind == "add_field" and change.collection == self.job["collection"]
                      and change.field == self.job["field"])
        change.note = note
        counts = defaultdict(Counter)
        for item in rejected:
            documents = {e["document_id"] for e in item["evidence"]}
            for document in documents or {"unknown"}:
                counts[document][item["reason"]] += 1
        self.metadata(rejected_fields={key: dict(value) for key, value in counts.items()})

    def sources_unchanged(self):
        # Recheck pinned bytes before committing; do not pin a new live document snapshot.
        load_pinned_contexts(self.store, self.revision, self.job["context_job_id"])

    def publication_unchanged(self):
        # A fill only adds candidates through review rules; human acceptances are preserved.
        if lifecycle.head(self.store, self.workspace) != self.job["base_revision_id"]:
            raise PipelineError("publication_changed")
