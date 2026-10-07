# wp90-m1-plan — PM: plan and run milestone U1 "the first release that works end to end" (not the old M1 = multi-format parse + canonical, which is done)

- Özet: PM (Slowking) U1'i planlar ve yürütür: tüm proje notlarını okur, U1 kapsamını kabul ölçütleriyle yazar, paralel iş paketlerini (WP) hazırlar, ilerlemeyi ve Notion'u takip eder.
- Model: derin
- Engine: codex
- Phase: U1
- Branch: `codex/wp90-m1-plan` (base: `origin/dev`)
- Role: pm

## Why (user, 2026-10-07)

"Tamamen çalışan bir ürün değil ama belli kısımlara kadar sorunsuz çalışan bir ürün görmek istiyorum, tam şu
an." The lead built many parts; no path works end to end without the lead running scripts by hand. The
user also expects the PM to own planning and the project notes.

## U1 golden path (the lead's proposal — validate it against the notes, improve it, keep it small)

1. Web: pick or create a company workspace, upload its documents (several files at once), see processing
   status in plain words.
2. "Bilgileri çıkar" in the web: discovery → schema review (auto-accept verified fields for U1) → extract →
   match → merge → publish runs as a worker job, with progress; the model is chosen per workspace in the
   web (settings), default off (ROADMAP decision 15) — without a model the button explains what to set.
3. Koleksiyonlar and Sorular work on the result; answering publishes approved values.
4. "Dene": ask a question in the web; the answer uses the AI tools (wp68) with sources, or says
   "Bilmiyorum".
5. A smoke test that walks this path on a synthetic company and reports pass/fail per step; U1 is done
   when it passes on the running stack and the lead confirms it on one real company.

Everything else (D3 versions, auth, embeddings, new UI ideas) waits until U1 passes.

## Tasks

1. Read the project notes: `C:/Users/root/Documents/projects/docgrain/.lead/notion-summary.md` (lead's summary of every Docgrain Notion page — do not
   copy it into git), `docs/plan/ROADMAP.md` (decisions 1–16), `docs/plan/wp/*.md`, README, `C:/Users/root/Documents/projects/docgrain/.lead/HANDOFF.md`.
   If you can reach Notion directly, read the Docgrain pages too.
2. Write `docs/plan/U1.md`: scope, the golden path as numbered user steps, acceptance checks per step,
   out-of-scope list, risks, and which existing code each step reuses (CLI `docgrain-records`,
   `docgrain ingest-folder`, `/ai` tools, review API, web screens) — with file paths.
3. Split U1 into 4–5 parallel work packages with **disjoint file ownership** and write each spec in
   `docs/plan/wp/` from `TEMPLATE.md` (Turkish `- Özet:` line, `- Model:`, `- Engine: codex`, UI WPs also
   `- Skill: frontend-design`; UI = Tailwind + shadcn only, no new .css). Suggested split: (a) pipeline job in
   worker/API with progress (orchestrates the existing CLI steps), (b) workspace settings: model choice
   per workspace + secrets handling, API + web, (c) web: upload many files + processing status + "Bilgileri
   çıkar" with progress, (d) "Dene" screen on the AI tools, (e) smoke test + synthetic company fixture.
   Name dependencies and the merge order.
4. Write `docs/plan/U1-checklist.md`: the manual acceptance walk the user can follow in 10 minutes.
5. Notion: if reachable, create a page "U1 — İlk uçtan uca sürüm" under Docgrain with the scope,
   WPs and checklist; otherwise put the Notion text in `docs/plan/U1-notion.md` for the lead to publish.

## Acceptance criteria

- [ ] `docs/plan/U1.md`, `U1-checklist.md`, and 4–5 WP specs exist, each WP with disjoint files, tests, and
      measurable acceptance.
- [ ] Report in Turkish: the plan in 10 lines, what you changed from the lead's proposal and why, risks.

## Notes

- Planning only: no product code. No git, no network installs. Never put customer names in committed files.
