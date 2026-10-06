# wp61-real-questions — ask only real conflicts, with document names

- Özet: Gerçek veride bazı "çelişkiler" aslında çoklu değer (tekrarlanan bir etkinliğin 9 tarihi); bunları soru yapma, "Hepsi doğru" seçeneği ekle ve seçeneklerde belge kimliği yerine dosya adını göster.
- Model: derin
- Phase: D4
- Branch: `codex/wp61-real-questions` (base: `origin/dev`)
- Depends on: wp59 (PR #40)
- Role: implementer

## Findings (lead, real workspace, 2026-10-06)

1. First question: "<event> · Tarih hangisi?" with 9 options, all from the same document at different
   locators — a recurring show with nine dates. All are true; asking "which one" is wrong.
2. `options[].document_name` shows document ids (`doc_1bce4d1f`) instead of the file name.

## Tasks

1. Multi-value detection when building questions: if all non-rejected candidates of a field/lang come
   from the same document and differ only by value (dates, times, prices per variant), or the schema
   field type is a list, treat it as a multi-valued field: no conflict question; publish the values as a
   list in preview. Keep it conservative and covered by tests; real conflicts across documents stay
   questions.
2. Answer `{ "all": true }` → every non-rejected candidate accepted as one list value (field becomes
   multi-valued for that record); response as other answers. Add `allow_all: true` on questions where
   the values could all be true (same field type is a scalar but candidates differ), so the UI can show
   "Hepsi doğru".
3. `document_name`: the source file name from the pinned `source.json` (fallback: document id), and
   `locator` as a human page/section label ("s. 2", "§ 4").
4. Summary `conflicts` counts only real questions after (1).

## Acceptance criteria

- [ ] `.venv/Scripts/python -m pytest -q tests/unit` and `ruff check apps packages tests` pass.
- [ ] Tests: recurring dates from one document → no question, list in preview; same field from two
      documents → question; `{all: true}` answer; file names in options.
- [ ] Report with before/after counts on a synthetic workspace modelled on the finding.
