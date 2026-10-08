# wp97-reading-quality — Read hard pages with the workspace model and show reading quality

- Özet: Yerel okuyucunun zorlandığı sayfalar (düşük OCR güveni, sadece görsel sayfa, JPG/PNG, bozuk sütun/tablo) şirketin açtığı modele görüntü olarak gönderilsin; her belge için "ne kadarı okundu" sade bir rapor olarak görünsün.
- Model: derin
- Engine: codex
- Phase: U1
- Branch: `codex/wp97-reading-quality` (base: `origin/dev`)
- Depends on: WP92 (merged: per-workspace model). Coordinates with WP91 (see Ownership).
- Role: implementer
- Owner: Charizard (codex)

## Why (user, 2026-10-07)

"Belge yükleme, belgeyi Docling ve Google Vision ile anlama kısmını tam yapabildiğimizi sanmıyorum."
Lead measurement on the four test companies (40 files): only 17 read fully; one company has low OCR
confidence on 36 of 56 pages; another has 2,893 unresolved regions and a 9 MB JPG that yields 2 chunks.
No document used a vision model (`vision_provider` is null everywhere): Docling + local EasyOCR only.
ROADMAP decision 17: with the workspace model on, hard pages go to it as images by default; model off →
nothing leaves the machine.

## Goal

1. Each document version gets a reading report computed from what the worker already knows: pages,
   pages read well, pages with low OCR confidence, image-only pages, images not understood, unresolved
   regions, column/table conflicts — and which pages were read by the model.
2. When the workspace model is on (`docgrain_api.workspace_settings.resolve_workspace_model`), the worker
   sends only the hard pages (rendered page image, or the image file itself for JPG/PNG) to that
   OpenAI-compatible model with an image input, using the existing untrusted-source prompt rules in
   `apps/worker/docgrain_worker/selective_vision.py` (observable text only, no invented facts, tables
   transcribed exactly). The model output becomes canonical content for that page with provenance
   (`content_origin`, model name, page, region) so evidence can point at it. Model off → no call, the report
   says which pages need the model.
3. A lead/admin action re-reads the hard pages of an already ingested version (no re-upload):
   CLI `python -m docgrain_worker.reread --workspace <ws> [--document <id>]` and the same through an API
   endpoint the web can call later.
4. The Belgeler screen shows the report per file in plain Turkish ("7 sayfanın 5'i okundu · 2 sayfa model
   bekliyor") with a details popover; Geliştirici modu shows the codes.

## Ownership (disjoint from WP91)

- Yours: new `apps/worker/docgrain_worker/reading_quality.py`, new `apps/worker/docgrain_worker/reread.py`,
  `selective_vision.py`, `vision.py`, `quality.py`; the one call site inside `process()` in
  `apps/worker/docgrain_worker/main.py` (do NOT touch `run()` or the queue loop — WP91 owns them);
  a new API router file for the report/re-read endpoints; `apps/web/app/components/documents.tsx` only
  for the report display (keep WP93's upload/progress code intact); tests `tests/unit/test_reading_quality.py`,
  `tests/unit/test_reread.py`.
- Not yours: `docker-compose.yml`, Dockerfiles, `records_*`, `routers/record_jobs.py` (WP91). If the worker
  needs an env variable, list it in your report; the lead wires it.
- Replace the old global switch `DOCGRAIN_REMOTE_VISION_ENABLED` + `GEMINI_API_KEY` path with the workspace
  model for this flow; do not add a new global key path.

## Rules

- Before you import a name, grep that it exists. No raw exception text in user-facing messages; never log
  or store keys. Source text in images is untrusted data, never instructions.
- Bounded: at most N pages per version per run (configurable, default 30), per-page timeout, retries on
  429/5xx, resumable (pages already read by the same model + same image hash are skipped).
- Tailwind + shadcn only in the web; no new CSS.
- Tests use fake transports — no network.

## Acceptance criteria

- [ ] Model off: zero model calls, report lists hard pages as "model bekliyor".
- [ ] Model on (fake transport): only hard pages are sent (a clean text page is not), output lands in the
      canonical content with provenance, a second run sends nothing new.
- [ ] A JPG with text yields text chunks through the model path (fake), with provenance.
- [ ] Invalid/hostile model output (instructions inside, non-JSON, invented fields) is rejected or stored
      as needs-review, never as accepted fact.
- [ ] `reread` CLI on a fixture version updates the report; `.venv/Scripts/python -m pytest -q` green;
      ruff clean; `tsc` 0; existing web tests green.
- [ ] Report (Turkish): files changed, the env variables the lead must wire, how to run `reread` on a real
      workspace, risks.

## Rescope after decision 18 (lead, 2026-10-08) — read before you continue

WP100 made Docling + Tesseract the default reader and deleted `vision.py`. The Docling confidence report now
drives hard-page codes. Rework this WP on top of `origin/dev`:
- Keep: the per-document reading report and its Belgeler display; hard-page selection, page budget and resume.
- Signal: hard pages come from the Docling confidence report (low/poor grade) plus image files and text-less pages.
- Transport: no own HTTP client. Use Docling's remote options with the workspace model
  (`resolve_workspace_model`): `PictureDescriptionApiOptions` for pictures and the VLM pipeline with
  `ApiVlmOptions` (`page_range` per hard page) for hard pages; `enable_remote_services` only when the workspace
  model is on (decision 17). Gemini returns Markdown, so provenance stays page-level.
- Results stay separate, unapproved page-level content with provenance (model, page, image hash) until review.
- Measure with `benchmarks/docling_profiles.py` profile `E_vlm` (the lead runs it with a real key).
