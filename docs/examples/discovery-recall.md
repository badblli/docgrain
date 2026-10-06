# Workspace discovery recall (wp57)

## Root cause

The detector discarded headings unless the exact heading occurred twice and had no section-text
fallback, leaving plain-text and noisy OCR blocks with few candidates. The model received only
signals with at most six samples per pattern, rather than every source block, and there was no
coverage check or second pass for omitted sections.

## Behavior and synthetic measurement

Discovery now retains singleton Markdown/plain headings, repeated label:value lines, lists,
tables/cards, measures, and every nonempty section body. All normalized source bodies are sent
in deterministic document/block order; oversized requests and blocks are split without dropping
characters and keep their original document IDs and evidence keys. Signal hints are capped at
20 patterns of 160 characters per request; source text is never sampled. Example quotes are
verified against the text actually supplied in that request.

`schema.proposed.json` includes `coverage` (0–1) and `uncovered` (distinct section titles).
Coverage counts the characters in nonempty source block bodies whose document ID and locator
are cited by a verified example; it excludes the locator footer, markers and filenames.
It measures evidence-linked block coverage, not semantic completeness or field accuracy:
one citation covers its whole block, even when the block contains several topics.

The first round scans every block. Remaining blocks trigger another round when at least 100
characters and more than 5% of the total remain uncovered. There are at most three rounds
(`--max-rounds 1`, `2`, or `3`), each potentially containing several bounded requests.
Same keys union fields/examples; incompatible types/units remain visible for review.
Residual gaps remain in the output, including when the model returns nothing or is disabled.
Review acceptance recomputes coverage after rejected collections/fields are removed.

Synthetic fixtures: a plain-text hotel with eight lists, and noisy short-line OCR with three
sections. The section-aware fake model discovers all eight lists; a fake first answer containing
only rooms is completed by a second request containing only the other seven sections.

| Fixture | Signals before | Signals after |
| --- | ---: | ---: |
| Existing hospitality table | 2 | 4 |
| Plain-text hotel | 6 | 27 |
| OCR-like hotel | 2 | 8 |

## Lead command for real workspaces

Run from this worktree. Set `DOCGRAIN_WORKSPACE_ID`, `DOCGRAIN_MODEL_BASE_URL`,
`DOCGRAIN_MODEL`, and `DOCGRAIN_MODEL_API_KEY` in the lead's environment (never print the key).
The API below must be the lead's local document service with the workspace already normalized;
change the local port if necessary. Repeat with each real workspace ID:

```powershell
$env:PYTHONPATH = 'packages/records;packages/domain;packages/evaluation'
& 'C:/Users/root/Documents/projects/docgrain/.venv/Scripts/python' -m docgrain_records discover `
  --workspace $env:DOCGRAIN_WORKSPACE_ID `
  --api http://localhost:8000 `
  --out ".lead/wp57/$env:DOCGRAIN_WORKSPACE_ID" `
  --base-url $env:DOCGRAIN_MODEL_BASE_URL `
  --model $env:DOCGRAIN_MODEL `
  --api-key-env DOCGRAIN_MODEL_API_KEY `
  --max-prompt-chars 120000 --max-rounds 3
```

Add `--dry-run` to inspect first-round request count/size without calling the model or writing
output. For an offline normalized export, replace `--api http://localhost:8000` with
`--sources '<directory containing source.json/context.md pairs>'`.
Without the three model configuration flags, discovery scans and reports gaps without model calls.
The worker used only synthetic fixtures and made no network/model calls to real services.
