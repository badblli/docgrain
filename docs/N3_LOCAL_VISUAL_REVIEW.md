# N3 local visual review

Implementation notes for ADR 0020. Status: local implementation; final verification evidence is added by Codex.

## Components

| Part | Role |
| --- | --- |
| `packages/domain/docgrain_domain/canonical/visuals.py` | Inventory, preview request/response, verification. No OCR, classifier or provider call. |
| `apps/worker/docgrain_worker/local_visual_ocr.py` | Selected CPU OCR session and proposal validation. |
| `apps/api/docgrain_api/routers/knowledge.py` | Read-only inventory GET and pure preview POST. |
| `apps/web/app/components/canonical/visual-review.tsx` | Inspector panel; downloads inventory/preview JSON. |
| `docs/examples/review_local_visuals.py` | CLI for inventory, preview and selected OCR. |

## Inventory

`visual_inventory(snapshot)` revalidates the snapshot and emits one region for every `asset`, `chart` and `table` node. Fields include evidence IDs, artifact ID, binary SHA-256, `binary_available`, `duplicate_of`, `native_chart_data` and `description_present`. Pictures the parser reported as `unextracted_picture` appear in `unresolved_picture_refs`; classification cannot close them.

Actions are derived, not inferred from content: `classify_visual` (assets), `review_table_source`, `missing_source_evidence`, `no_raster_binary`, `local_ocr_available` (PNG/JPEG source-image artifact with evidence), `visual_meaning_unresolved`, `inspect_native_chart_data`.

The inventory binds workspace, document, revision, source SHA-256 and snapshot SHA-256. Its ID is a digest of its content. `verify_inventory` rejects an inventory that differs from the snapshot.

## Classification preview

Request (`VisualPreviewRequest`): `inventory_id`, `snapshot_sha256`, and 1–10,000 decisions of `{region_id, classification, reviewer_id, reason}`. Reviewer and reason must be nonblank.

Rejected with 409 (API) / `ValueError` (library): stale inventory or snapshot hash, unknown or duplicate region, relabeling a native table/chart, or a region with no source evidence.

Output is `docgrain.visual-review` 1.0.0, `review_status: proposed`, decisions sorted by region ID. Labels are manual proposals. A repeated binary is not treated as decorative. Logo/decorative proposals do not remove binaries or close quality gaps.

## API

- `GET /v1/knowledge/revisions/{revision_id}/visuals` — read-only.
- `POST /v1/knowledge/revisions/{revision_id}/visuals/preview` — pure; no persistence, no accepted revision, no embedding, no model call.

Existing normalizations, binaries and history are not modified. N4 applies reviewed changes with CAS later.

## Selected local OCR

- Reader: EasyOCR 1.7.2, `["tr","en"]`, CPU, `download_enabled=False`, weights from the verified model directory (no runtime downloads). Direct reader call; no Docling layout for the selected artifact.
- Options: greedy decoder, `batch_size=1`, `workers=0`, `canvas_size=2560`, `mag_ratio=1.0`; profile `n3-local-1`.
- Input checks: source bytes match pinned source hash and size; image bytes match artifact hash and size; PNG/JPEG format verified; at most 20,000,000 pixels. Output retains at most 10,000 words; excess observations cause `ocr_word_limit` and are not cached.
- Request binding: inventory, snapshot, document, workspace, revision, source hash, region, node, evidence IDs, artifact, binary hash, prepared-input hash and original geometry (pixel size, EXIF orientation).
- Reuse: the session keeps one reader and an in-memory cache (64 entries) of OCR observations keyed by input hash and profile. Bindings are rebuilt on every call, so a cache hit never carries another source's bindings.
- Successful output: `docgrain.local-ocr-proposal` 1.0.0, `review_status: proposed`, words with scores (`easyocr-recognition`) and original-pixel locators, `visible_text`, `visual_description: null`. Uncertainties include `visual_meaning_unresolved`, plus `ocr_low_score`, `no_readable_text`, `ocr_word_limit` as applicable.
- Literal unreviewed OCR is not plan, diagram or chart meaning.
- Verified reader initialization, recognition and malformed recognition output failures yield `execution_status: failed`, a stable category, no words or observation digest, and no cache insertion. Unverified profiles fail closed. Failed proposals cannot carry observations. Only validated finite coordinates/scores and valid image geometry enter the cache; arbitrary exception strings are not published.
- `validate_local_ocr_proposal` rechecks bindings, profile, word frames, text/word parity and the observation digest.

## Remote vision

Disabled by default: `DOCGRAIN_REMOTE_VISION_ENABLED=false`. `GEMINI_API_KEY` alone does not activate remote calls in the worker. The existing selected remote runner (`extract_selected_visual.py`) requires `--allow-remote` for new requests. The five previously authorized Gemini proposals stay historical/proposed. This document does not claim that all external-provider code is removed.

## CLI

```
review_local_visuals.py --snapshot SNAPSHOT.json --output NEW_DIR
    [--decisions DECISIONS.json]
    [--ocr-inputs INPUTS.json --source ORIGINAL_SOURCE]
```

- Inventory only: with just `--snapshot` and `--output` it writes `<inventory-id>.json`.
- `--decisions`: a `VisualPreviewRequest` JSON; writes `<review-id>.json`.
- `--ocr-inputs`: JSON `[{"region_id": ..., "image_path": ...}]`, 1–100 selections; requires `--source`. Writes `<region_id>-ocr.json`.
- Existing successful proposals are validated against the current bindings and reused without inference; they are immutable.
- A failed proposal is retained. To retry, use a new output folder.
- No network, no canonical write, no model download.

## UI

The inspector panel loads the inventory, lets a reviewer choose a type label for asset regions, and downloads the inventory or the preview JSON. Nothing is saved server-side. Native tables/charts show source structure only. The panel states that labels are not acceptance of classification, OCR or visual meaning.

## Known limits

- Binary availability reflects an artifact pointer; storage health is not established.
- No timeout or worker-recovery certification for local OCR.
- No local visual semantic model has been chosen or accepted. Plans, diagrams and charts have no automated meaning.
- Tables still need source review.
- N3 full semantic gate, N4 (reviewed reconciliation with CAS) and N5 (corpus acceptance) are open. Embedding follows N5.

## Verified local evidence — 2026-10-02

- Full worker/Docling/EasyOCR/PostgreSQL/MinIO suite: **310 passed, 0 skipped**. Host: 234 passed, 76 dependency/service tests skipped. Includes actual CPU OCR and EXIF/repeated-binary reuse, malformed observations, initialization/recognizer failures, stale proposals, pure API previews and configured-key-without-remote-opt-in tests.
- Ruff error checks, production web build with TypeScript, API/web/worker images and Compose config passed. Stack uses `data/reviews/n3-local.compose.yml`; remote Vision disabled and worker key blank.
- Five live inventory responses match the retained source snapshots. Two PDF inventories contain 23 assets (10 Dobedan, 13 Corendon); proposed source-image classifications are 10 logos, 9 photos and 4 plans. Labels remain local previews. The five snapshots also retain 34 table nodes; neither labels nor successful OCR accept their cells.
- Actual selected OCR: two nodes sharing a logo binary reuse one observation; four room plans return no readable text. Logo OCR returns `D 0 B E D A` with low-score uncertainty, not accepted spelling. No plan dimensions or descriptions are inferred.
- A single selected-artifact session measured reader initialization at 5.1473 s; individual warm plan totals 0.0526–0.2451 s and the repeated logo cache hit 0.0328 s. This is six selections of small retained assets, not full-document throughput, p95 or a deployment SLA. No Docling reparse or visual semantic model ran.
- Browser: real Corendon Assets panel reports 13 visuals/4 tables/13 unknown. A Plan proposal downloads with the correct source/revision binding and proposed status. Two synchronous clicks with a delayed request issue one POST; UI handles duplicate saves, stale revision inventory and missing evidence. Console reports zero errors.
- Five live heads unchanged; 30 stored and 30 regenerated output hashes match the pre-N1 baseline after deployment and preview. No user-source ingestion, document deletion, new normalization-provider or embedding call.
- Claude produced OCR fixes/regressions, documentation drafts and a UI/API review from code-only scratch copies. Codex reviewed/applied them and ran the checks; Git/GitHub and Notion remain under Codex management. No user source documents were supplied to Claude.

Ignored local evidence: `data/reviews/n3-tests.xml`, `n3-host-tests.xml`, `n3-source-review/report.json`, `n3-live-api.json`, `n3-live-parity.json`, `n3-claude-*`.

The local inventory/OCR foundation is verified. The N3 visual semantic model/meaning gate, N4 immutable reviewed apply and N5 corpus acceptance remain open. Embedding is still last.
