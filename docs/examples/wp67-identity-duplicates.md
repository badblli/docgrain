# WP67: identity and duplicate review

All examples below are synthetic. No model or external service is used by identity selection,
duplicate detection, answering or the offline report.

| Synthetic finding | Before | After |
| --- | --- | --- |
| FAQ fields ordered `answer`, `question` | Title: `Evet var.` | Newly accepted schema pins `identity: question`; title: `Otopark var mı?` |
| Five room records: two Cedar variants, three Maple variants; equal capacity and size | Five separate records, no duplicate question | Five separate records, four pair questions (two groups); no automatic merge |
| Two Cedar variants with different views; answer `{"same": true}` | Two records, one duplicate question | One record, two ordinary conflicts (`name`, `view`); shared capacity and size retain evidence from both documents |
| Same pair; answer `{"same": false}` | Two records, one duplicate question | Two records, no repeat question; veto survives restart, other answers and a fresh publication with the same stable record IDs |

`duplicates` counts **pairs**, not groups, at workspace and collection level. Duplicate questions
are separate from `conflicts` and appear after conflicts, before `needs_review`. All fields stay
evidenced. An identity answer does not approve previously proposed facts. Different scalar values
approved in the separate records return to review after consolidation.

The score requires a distinctive normalized name (Turkish character folding, token sorting and
room/suite stop words), plus at least one matching field. Near names need two matching fields.
Name similarity must be at least 0.92; the score must be at least 0.85. Contradictory shared fields
reduce the score. Only an explicit `same: true` answer merges records. The smaller stable record ID
is kept. `duplicate_decisions` records the pair, decision, local actor and timestamp.

The web card shows both titles, up to four compact fields and source quotes. Its actions send
`{"same": true}`, `{"same": false}`, or `{"skip": true}`. Same/different answers publish a child
revision; skip follows WP59 and only defers the question. Existing immutable publications remain
readable. Rejected pairs are carried into new publication snapshots; staged retries remain stable.

## Re-run on synthetic data (PowerShell, repository root)

```powershell
$python = 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python'
$env:PYTEST_ADDOPTS = '--basetemp=.pytest_cache/wp67-check'
& $python -m pytest -q tests/unit/test_identity_duplicates.py
& $python -m pytest -q tests/unit
& $python -m ruff check apps packages tests
$env:NODE_OPTIONS = '--preserve-symlinks --preserve-symlinks-main'
node apps/web/node_modules/typescript/bin/tsc --noEmit -p apps/web
node --test apps/web/app/components/workspace-review.test.cjs
```

The temporary-directory setting avoids the restricted shared Windows pytest directory. Node's
options avoid restricted parent-directory realpath calls. From `apps/web`,
`npx tsc --noEmit -p .` uses the same installed TypeScript compiler without a registry download.

## Lead re-run on private data

Use a private merged revision's JSON file, outside Git. This command prints counts only, never
titles, quotes or source content. Replace the example path with the private revision path.

```powershell
$python = 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python'
$env:PYTHONPATH = 'apps/api;apps/worker;packages/domain;packages/evaluation;packages/records;packages/ingestion'
$privateRevision = 'C:/private/workspace/merge.revision.json'
& $python -c 'import json, sys; from collections import Counter; from pathlib import Path; from docgrain_records.export import load_revision; from docgrain_records.review import questions, summary; r = load_revision(Path(sys.argv[1]).read_bytes()); s = summary(r, "offline"); print(json.dumps({"records": s["records"], "duplicates": s["duplicates"], "conflicts": s["conflicts"], "unsupported_fields": s["unsupported_fields"], "question_kinds": dict(Counter(q["kind"] for q in questions(r)))}, ensure_ascii=False))' $privateRevision
```

Old schema versions intentionally keep their original identity behaviour. To check the FAQ fix on
private data, accept a **new** schema version from the reviewed proposal and its pinned contexts:

```powershell
$privateSchema = 'C:/private/workspace/schema'
& $python -m docgrain_records.cli accept-schema --proposal "$privateSchema/schema.proposed.json" --out $privateSchema
```

Then use that new `schema.v<N>.json` in the lead's existing explicitly enabled extraction/merge
run, publish the resulting new revision, and run the count command above on it. The lead checks
real titles and card layout in the web and runs the production build. No private data is needed in
the public test suite.
