# Docgrain roadmap (D1–D7)

Mirror of the Notion page "Docgrain — Ürün yönü ve yol haritası (D0–D7)". Notion is the
discussion copy; this file is what workers read. Tech lead: Claude Code. Updated 2026-10-05.

## Goal

Normalize a company's PDF, DOCX, XLSX, TXT and PNG/JPEG documents into one canonical model,
version it without full reprocessing, extract typed collections (rooms, restaurants, bars,
activities, meeting rooms, services/prices, policies, contact) as one shared data pool, and let
any OpenAI-compatible AI answer quickly and correctly from it — the same accepted data also feeds
mobile apps and websites.

## Glossary (code name → UI name)

| Code | Meaning | UI (Turkish) |
| --- | --- | --- |
| `Workspace` | One company/customer; all data lives under it | Çalışma alanı |
| `Document` | Logical document; may have several file versions | Belge |
| `SourceVersion` | One immutable uploaded file version | Dosya sürümü |
| canonical model / `KnowledgeRevision` | Normalized, source-linked document state; each edit is a new revision | Belge içeriği / Düzenleme geçmişi |
| `Evidence` | Where a fact is in the source (page, cell, box) | Kaynakta göster |
| `Collection` | Typed list (Rooms, Restaurants…); schema from a domain pack | Bilgi listesi |
| `Record` (today: entity) | One item in a collection; fields linked to evidence | Kayıt |
| `ReviewState` | `proposed` → `needs_review` → `accepted` / `rejected` | Öneri / İnceleme bekliyor / Onaylandı / Reddedildi |
| `KnowledgeTree` | Tree of sections/tables/records for navigation (PageIndex-style) | İçindekiler |
| `KnowledgePack` | Published, accepted, versioned output of a workspace | Yayın |
| `DomainPack` | Industry schema set, e.g. `hospitality`; never in core | Şablon |
| `ExternalAsset` | Image/file referenced by URL inside a source | Dış bağlantı |

## Decisions

1. Canonical model is the single source of truth; everything else is derived.
2. Embeddings are optional and off the critical path. Small/medium data: compact direct context.
   Large data: tool-based tree navigation. Add embeddings only if D1 measurements require it.
3. Model-agnostic: AI access uses OpenAI-compatible chat + function-calling schemas. Provider-specific
   code is an adapter.
4. PageIndex idea as tools (`get_tree`, `get_node`, `list_collection`, `get_record`, `search_text`),
   not a copy of PageIndex.
5. Docgrain is not a chatbot. It serves packs, APIs and tool specs; a "Dene" screen exists for testing.
6. Instruction-like text inside sources is data (`untrusted_instruction`), never system authority.
7. Nothing is "done" without measurement against golden questions/tables (D1).
8. End users are non-technical hotel staff. Default UI has no technical terms; developer views sit
   behind a "Geliştirici modu" switch.
9. External image URLs in sources are stored as `ExternalAsset` links; downloading requires an
   explicit user action.
10. Existing M2 code (retrieval, lifecycle, live sources) is reused, not extended, until a phase needs it.
11. User decision 2026-10-05: measurement (D1) and development may send normalized content of the
    current hotel documents to a cloud model (Gemini via its OpenAI-compatible endpoint). In the
    product each workspace chooses its model; LLM calls stay off by default.

## Phases

- **D1 Measurement** — golden corpus, ≥40 golden questions (incl. unanswerable), table goldens,
  `docgrain eval` against any OpenAI-compatible model; record a baseline.
- **D2 Extraction fixes** — flattened markdown tables → real tables, `ExternalAsset`,
  `untrusted_instruction`, honest status labels. Accept: `doobedan_full` table cells ≥95 %, eval
  score up, no regressions.
- **D3 File versions** — upload a new version of an existing document, canonical diff, "Neler
  değişti" view, carry accepted edits forward. Accept: one-word DOCX change shows only that block.
- **D4 Collections** — `hospitality` domain pack, LLM-proposed records with evidence, multi-document
  merge with visible conflicts, review UI. Accept: ≥95 % fields correct, 0 fields without evidence.
- **D5 Access layer** — read-only REST for apps (collections/records/tree, ETag), precomputed AI
  context, OpenAI tool specs (+ optional MCP), "Dene" screen. Accept: D1 above threshold on two
  different models; direct-context prep p95 < 100 ms.
- **D6 Change propagation** — edit/new version republishes only affected parts atomically; webhook
  events. Accept: one field edit visible to AI within seconds; old revision still queryable.
- **D7 Simple UI** (parallel from D3) — screens: Belgeler, Belge (Oku / Değişenler / Geçmiş),
  Bilgi (collection cards), Dene. One primary action per screen; mobile 390 px without overflow.
- Later: E (embeddings/Qdrant, only if measured need), P (auth, multi-tenant isolation, queue
  recovery, deploy).

## Team process

- Lead (Claude Code) writes WPs in `docs/plan/wp/`, assigns them to named Codex agents
  (`docs/plan/team.json`), reviews diffs, runs acceptance, decides, and commits/pushes/opens PRs.
- Codex agents implement one WP each in `../docgrain-wt/<wp-id>` on `codex/<wp-id>`
  (`scripts/team/run-wp.sh`), sandboxed, without Git writes. Lead feedback: `scripts/team/tell.sh`.
- Codex keeps Notion progress notes.
- Critical product/privacy decisions go to the user.
