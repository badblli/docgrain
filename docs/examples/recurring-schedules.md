# Tekrarlayan etkinlik takvimleri

WP64 compares date fields offline, using at least three dates per document. It fits
weekly or fortnightly rules with repeated weekdays and limited missing/extra dates.
The observed date list remains authoritative; inference neither adds dates nor accepts facts.
Readable summaries live beside the field under `_meta.fields.<field>.schedule` and in
the compact context output. The record detail view displays `schedule.label_tr`.

Documents with the same rule and agreeing dates in overlapping coverage publish their union
in preview, retaining both documents' evidence. A missing/extra date inside that coverage
produces one `schedule_conflict` question with only the differing dates in its options.
Partial coverage extending the same rule does not create a question.

Two records in the same collection produce one `schedule_swap` question when the two source
programs exactly cross-match for a recurring period, with at least three exchanged dates in
each direction. Partial matches or a third source remain separate questions. Questions expose
`records` (titles), `record_ids`, `period_label_tr`, `question_tr` and source-grouped options
with `summary_tr`, the full `program` and citations. Answering `{ "document_id": "..." }`
accepts that source's complete date lists for both records in one immutable child revision.
Each record receives its own history entry under the same question ID. Schedule questions
accept document choices or deferral; the card shows those actions.

The synthetic May–September Saturday fixture has three shared May–June dates per record,
then exchanges the two fortnightly series from July. The previous scalar question flow had
**2 questions × 16 date options**. WP64 produces **1 `schedule_swap` × 2 document options**.
The answer publishes both chosen programs; the base revision's bytes remain unchanged.

## Lead verification

Run from this worktree, with the repository venv. In restricted Windows sessions, keep
temporary test files in the worktree:

```powershell
New-Item -ItemType Directory -Force .pytest_cache/wp64-tmp | Out-Null
$env:TEMP = (Resolve-Path .pytest_cache/wp64-tmp).Path
$env:TMP = $env:TEMP
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m pytest -q tests/unit/test_recurring_schedules.py
```

For the real run, set `MERGE_REVISION_FILE` to the existing aggregate `merge_revision.json`
or publication `source.json` locally. This command reads that revision with the new code,
uses no model/network calls and prints only counts, never titles, dates, quotes or filenames:

```powershell
$env:PYTHONPATH = 'packages/records;packages/domain'
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -c 'import json,sys; from pathlib import Path; from collections import Counter; from docgrain_records.export import load_revision; from docgrain_records.review import questions; items=questions(load_revision(Path(sys.argv[1]).read_bytes())); print(json.dumps({"total":len(items),"kinds":dict(Counter(q["kind"] for q in items)),"schedule_option_counts":[len(q["options"]) for q in items if q["kind"].startswith("schedule_")]},sort_keys=True))' $env:MERGE_REVISION_FILE
```

Existing publications are immutable. To verify the union/summary in the real publication,
publish a new revision through the lead's existing preparation workflow; do not regenerate
or overwrite the previous revision's published files.
