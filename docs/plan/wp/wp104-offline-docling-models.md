# wp104-offline-docling-models — Bake Docling models into the worker image; run offline

- Özet: Worker imajı Docling'in yerleşim, tablo ve resim sınıflandırma modellerini derleme sırasında içine alsın; çalışırken internetten model indirmesin ve ağ yokken de belge okuyabilsin.
- Model: hızlı
- Engine: codex
- Phase: D18
- Branch: `codex/wp104-offline-docling-models` (base: `origin/dev`)
- Depends on: WP100 (merged)
- Role: implementer
- Owner: Porygon (codex)

## Why (lead, 2026-10-08)

Running the default reader in the worker image with `--network none` and `HF_HUB_OFFLINE=1` failed every PDF
with `LocalEntryNotFoundError`: Docling downloads its models at first use. A local-first product (decisions 15
and 17) must read documents without network.

## Goal

1. `apps/worker/Dockerfile`: download the exact Docling model artifacts the default profile and profiles B/D need
   (layout, TableFormer accurate, picture classifier) at build time into a fixed path (e.g.
   `/opt/docling-models`), pinned by revision, and point the pipeline `artifacts_path` there.
2. Worker runs with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` by default in Compose.
3. A startup self-check logs a clear error if a required artifact is missing (no download attempt).

## Acceptance criteria

- [ ] The lead can run `benchmarks/docling_profiles.py --profiles C_tesseract` in the image with `--network none`
      and get the same results as with network.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean. Report (Turkish) with image size before/after.
