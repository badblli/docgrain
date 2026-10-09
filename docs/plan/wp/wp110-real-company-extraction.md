# wp110-real-company-extraction — Bilgileri çıkar must finish on real companies

- Özet: Bilgileri çıkar sentetik şirkette çalışıyor ama gerçek şirketlerde tek bir reddedilen alan, tek bir başarısız model çağrısı ya da doğrulanamayan tek bir şema alanı yüzünden duruyor; işi bu durumlarda tamamlayıp eksikleri raporla, çıkarmayı hızlandır.
- Model: derin
- Engine: claude
- Phase: U1
- Branch: `codex/wp110-real-company-extraction` (base: `origin/dev`)
- Depends on: WP91, WP102, PR #82 (merged)
- Role: implementer
- Owner: Claude agent (Codex at its usage limit)

## Why (lead, first runs on real companies, 2026-10-09)

- Company with 8 documents: after 18 minutes the job failed (`incomplete`) on the FIRST document: 15 records
  extracted, 7 fields rejected by the verifier (`duplicate_language`), 1 section failed with `connection_error`
  after 3 retries. `records_pipeline.py::extract` raises `incomplete` on any failure or rejection.
- Company with 5 documents (same concept in 4 languages): the job stopped at `accept_schema` with
  `needs_review` because one discovered field could not be verified — and there is no screen to review a schema.
- Extraction calls run one at a time (`concurrency=1`), so a company takes 15–30 minutes.

## Goal

1. Rejected fields never fail the job: they are the verifier doing its job. Count them per document and kind in
   the job metadata and the summary (`rejected_fields`).
2. Failed sections (model/network errors after retries): retry each failed section once more at the end of the
   stage; if it still fails, continue. The job finishes `done` with a clear note ("N bölüm okunamadı") and the
   failed sections listed in metadata, unless more than 20 % of sections failed (then `failed`, message says so).
3. Schema acceptance: accept every collection/field whose examples verify and that has no alternatives; set the
   others aside (kept in the proposal as `needs_review`, listed in metadata and the summary as
   "incelenmeyi bekleyen yapı") instead of stopping. Fail only when nothing verifiable remains. Keep the existing
   rule metadata (`reviewer: rule:u1-verified-schema`).
4. Extraction concurrency 4 (configurable), keeping deterministic record order and the per-call usage accounting.
5. The web progress/summary shows the new notes in plain Turkish (Tailwind + shadcn only) — small change in the
   existing components.

## Rules

Do not delete code; replaced code stays marked "KULLANILMIYOR (karar 18)". No network in tests (fake transports).
Keep publication fencing and stale-job behaviour from WP91/WP105.

## Acceptance criteria

- [ ] Fake-model tests: a document with rejections → job `done`, rejections counted; one section failing twice →
      `done` with the note; > 20 % failing → `failed`; one unverifiable schema field → other collections extracted,
      field listed as needing review; nothing verifiable → `failed`/`needs_review` as today.
- [ ] Concurrency 4 gives identical outputs to concurrency 1 on the fake model.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean, tsc 0. Report (Turkish) with the lead's live commands.
