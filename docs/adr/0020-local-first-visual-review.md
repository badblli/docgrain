# ADR 0020 — Local-first visual review for N3

Default reader/OCR signals superseded by [ADR 0024 — Docling reads documents](0024-docling-reads-documents.md).
Selected-artifact tools, visual inventory and human review contracts remain.

- Date: 2026-10-02
- Status: N3 local implementation; semantic gate, N4 and N5 remain open.

## Decision

For current N3, Docgrain owns visual inventory, classification review and OCR evidence locally. This supersedes the "selected remote provider" choice for visual interpretation in ADR 0017 (`Existing configured Gemini, explicit selected proposals`). The previously authorized five Gemini proposals remain historical and proposed; they are not deleted, accepted or reinterpreted.

Reasons: the product needs owned, local normalization and explicit revision control, and CPU-first operation. The Claude coding assistant that helps develop Docgrain is a separate concern and is not part of document normalization.

Embedding is unchanged from ADR 0017: it comes last, after N5.

## Contract

- **Inventory.** `docgrain.visual-inventory` 1.0.0 is derived from one canonical snapshot and binds workspace, document, revision, source SHA-256 and snapshot SHA-256. It lists every asset, chart and table region plus unresolved-picture references from parse issues. Region IDs derive from revision, node and evidence IDs.
- **Review preview.** `docgrain.visual-review` 1.0.0 carries manual type labels (`unknown`, `logo`, `decorative`, `photo`, `table`, `plan`, `diagram`, `chart`) with reviewer and reason. It is always `proposed`. Native table/chart kinds cannot be relabeled, unknown or duplicate regions are rejected, and a label requires source evidence.
- **Duplicates.** A repeated binary hash is recorded as `duplicate_of`. It is never evidence that a picture is decorative.
- **No schema bump.** Canonical schema is unchanged. The inventory and review sidecars are new 1.0.0 formats.
- **API.** `GET /v1/knowledge/revisions/{revision}/visuals` is read-only. `POST .../visuals/preview` is pure: no persistence, no accepted revision, no embedding. A stale inventory ID or snapshot hash returns 409.
- **Immutability.** Existing normalizations, binaries and history are unchanged. N4 later applies reviewed changes as new immutable revisions with CAS.

## Local OCR

Selected OCR calls the pinned EasyOCR 1.7.2 TR/EN reader directly on CPU, with weights loaded from the verified local model directory and downloads disabled. It does not run Docling layout for the selected artifact. One reader is reused per session, and cached observations are reused with fresh source/revision/region bindings.

A request binds source and image hashes and sizes, the original encoded pixel size and EXIF orientation. Word boxes refer to original artifact pixels. Bounds: 20,000,000 pixels and 10,000 words per image.

Literal OCR text is an unreviewed observation. It is not a plan, diagram or chart description, and `visual_description` stays null. A local visual semantic model has not been chosen or accepted.

## Remote calls

Remote vision is disabled by default: `DOCGRAIN_REMOTE_VISION_ENABLED=false`. `GEMINI_API_KEY` alone does not activate remote calls in the worker. The existing selected remote runner requires `--allow-remote` for new requests. This ADR does not claim that all external-provider code has been removed.

## Consequences and limits

- Artifact binary availability is a recorded pointer, not a storage health check.
- No timeout or worker-recovery certification exists for local OCR.
- Tables still require source review.
- The N3 full semantic gate, N4 reconciliation and N5 acceptance are open. Classification, OCR and scores cannot close source acceptance gaps.
