# wp50-company-bundle-ingest — Ingest a company's whole folder in one go

- Özet: Bir şirketin bütün dosyalarını (PDF, Word, Excel, metin, görsel) tek komutla kendi çalışma alanına yükle; tekrarları atla, durumu raporla.
- Model: standart
- Phase: D3
- Branch: `codex/wp50-company-bundle-ingest` (base: `origin/dev`)
- Depends on: none
- Role: implementer

## Goal
Each company is one workspace. Loading a company must be one action so we can compare how well
extraction/normalization works across different companies.

## Tasks
1. CLI `docgrain ingest-folder <path> --workspace <id> [--api URL]`: walks supported files
   (pdf, docx, xlsx, txt, png, jpg/jpeg; skip others with a reason), registers/uploads/confirms
   through the existing API, idempotent by content SHA-256 (same file twice → reused document),
   waits for processing, writes a bundle report (file → document id, status, pages, issues).
2. Workspace id must be honored end to end (API, storage paths, listing filter). If the API only
   supports `ws_local`, add the minimal workspace parameter needed; do not add auth.
3. Tests with synthetic files and a fake API transport; one integration test path documented.

## Acceptance criteria
- [ ] Ruff + pytest clean (repo venv); web build untouched.
- [ ] Re-running the same folder creates no duplicates (test).
- [ ] Report the exact command for the lead to load four companies into four workspaces.
