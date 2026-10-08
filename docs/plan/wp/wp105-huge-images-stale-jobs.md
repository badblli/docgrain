# wp105-huge-images-stale-jobs — Huge images must not crash the worker; crashed jobs must recover

- Özet: Çok büyük görseller (ör. 14.800×8.288 piksellik harita) okunmadan önce güvenli bir boyuta küçültülsün; worker çökerse yarım kalan işler sonsuza dek "çalışıyor" kalmasın, yeniden denensin ya da anlaşılır bir hatayla bitsin.
- Model: derin
- Engine: codex
- Phase: D18
- Branch: `codex/wp105-huge-images-stale-jobs` (base: `origin/dev`)
- Depends on: WP100, WP104 (merged)
- Role: implementer
- Owner: Porygon (codex)

## Why (lead, 2026-10-08)

Two map JPEGs of 14,800 × 8,288 px (122 MP, 15 MB each) crashed the worker container during full-page OCR (twice:
7 and 8 October). The container restarted, but the document jobs stayed `running` forever and the folder
ingest waited on them (per-file timeout 3 h). Four orphaned `running` jobs exist in the dev database.

## Goal

1. Image budget before Docling: images (JPG/PNG and PDF page images used for OCR) larger than a configurable
   limit (default: longest side 6,000 px and at most 40 MP) are downscaled with a high-quality filter, keeping the
   aspect ratio. The canonical locator keeps coordinates in the ORIGINAL image space (store the scale factor and
   map boxes back). Record an issue code `image_downscaled` with original and used size.
2. Very large images that are still too big or fail are split into overlapping tiles (optional, behind a flag) —
   if you implement tiling, boxes must map back to original coordinates; otherwise document why not.
3. Memory guard: conversion of one document runs in a child process with a memory/time limit, so a crash fails
   that job (`failed`, issue `worker_crash`) instead of killing the worker loop.
4. Stale job recovery: on worker start and periodically, document jobs in `running` without progress for longer
   than a limit (default 15 min) are re-queued once; a second stale run marks them `failed` with
   `worker_stale`. The ingest client then moves on.
5. Tests with synthetic large images (generated, not committed binaries) and a simulated crashed child.

## Acceptance criteria

- [ ] A synthetic 15,000 × 8,000 image converts without crashing; boxes map back to original coordinates.
- [ ] A child crash yields `failed` for that job and the worker keeps serving the next job.
- [ ] A `running` job older than the limit is re-queued once, then failed.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean. Report (Turkish) with the lead's live check commands.
