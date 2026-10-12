# wp116-user-schema-and-records — Users can add fields, items and collections

- Özet: Kullanıcı keşfedilen şemaya yeni alan ve yeni koleksiyon, bir koleksiyona da yeni kayıt (öğe) ekleyebilsin; eklenen alan model açıksa belgelerden kaynaklı doldurulmaya çalışılsın, belgede olmayan değerler "kullanıcı girdi" kanıtıyla tutulsun ve her ekleme revizyon geçmişine yazılsın.
- Model: derin
- Engine: codex
- Skill: frontend-design
- Phase: U1
- Branch: `codex/wp116-user-schema-and-records` (base: `origin/dev`)
- Depends on: WP110, WP111 (merged); coordinate with WP114/WP115 (records package) — avoid `match*.py`, `merge.py`,
  `extractor.py` edits beyond a clearly separated new function
- Role: implementer
- Owner: Jigglypuff (codex)

## Why (user, 2026-10-12)

"Şemaya ek alanlar ve ek itemler eklenebilmesi; bunları desteklememiz." Collections and fields are discovered
per company from its documents (discover → verified examples → accepted schema → extraction). Today users can
answer questions and correct values (`{value, note}` → `user_edit` evidence) but cannot change the schema or add
records.

## Goal

1. Schema edits (API + store, versioned like accept-schema): add a field to a collection (key, Turkish label,
   type from the existing type set, optional description), add a new collection (key, label, identity field,
   fields). Each edit creates a new schema version with the user as reviewer; nothing discovered is removed.
2. Fill a new field from documents: when the workspace model is on, a targeted extraction for just that field over
   the company's documents (reuse the extractor with a one-field runtime; evidence verified by `verify.py`) and
   publish through the normal merge/review rules (decision 20 auto-accept applies; conflicts become questions).
   When the model is off, the field stays empty with a clear note.
3. Manual values and records: set a value for any field of a record, and add a new record to a collection, with
   `user_edit` evidence (who, when, note) — shown as "Kullanıcı girdi" in the web, never as a document source.
   They go into the next approved revision via the existing revision/answer machinery (immutable history).
4. Web (Tailwind + shadcn only, no new CSS): in Koleksiyonlar — "Alan ekle", "Koleksiyon ekle", "Kayıt ekle"
   actions, a value edit on each field, and a visible source badge (belge / kullanıcı). Plain Turkish; codes only in
   Geliştirici modu.
5. AI access and Dene see user values with their `user_edit` source like any other approved value.

## Rules

Do not delete code (mark replaced code "KULLANILMIYOR (karar 18)"). No real model in tests. Keep publication
fencing (a running record job blocks schema edits with a clear 409).

## Acceptance criteria

- [ ] Tests: add field → schema version +1, old records intact; targeted fill with a fake model → verified values,
      unverifiable rejected; add record and manual value → `user_edit` evidence in the approved revision; edit blocked
      while a record job runs.
- [ ] `.venv/Scripts/python -m pytest -q` green, ruff clean, tsc 0, web tests green.
- [ ] Report (Turkish) with screenshots-free description of the new UI and the lead's live check steps.
